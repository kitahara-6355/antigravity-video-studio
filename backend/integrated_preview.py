"""
Integrated Preview with Subtitles
ロゴ+テロップ+字幕の統合プレビュー
"""

import subprocess
from pathlib import Path
import logging
import shutil

from path_resolver import raw_videos_dir

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_initial_segment(input_video: str, output_path: str, duration_sec: float = 10.0) -> None:
    """
    ffmpeg を使用して動画の最初の部分を指定秒数抽出する
    """
    logger.info(f"1. Extracting {duration_sec} seconds...")
    extract_cmd = [
        "ffmpeg",
        "-i", input_video,
        "-t", str(int(duration_sec)),
        "-c:v", "libx264",
        "-c:a", "copy",
        "-y",
        output_path
    ]
    subprocess.run(extract_cmd, check=True, capture_output=True)


def _apply_brand_logo_and_telop(input_video: str, output_path: str, logo_height: int, telop_duration: float = 10.0) -> None:
    """
    CombinedOverlay を使用して動画にロゴとテロップを適用する
    """
    logger.info("2. Applying logo + telop...")
    from combined_overlay import CombinedOverlay
    overlay = CombinedOverlay()
    
    overlay.apply_brand_overlay(
        input_video=input_video,
        output_path=output_path,
        speaker1="北原美麗",
        speaker2="山田タロウ",
        theme="想いを筆で起こす",
        logo_height=logo_height,
        telop_duration=telop_duration
    )


def _burn_subtitles_to_video(
    input_video: str,
    subtitle_file: str,
    output_path: str,
    design_name: str
) -> str:
    """
    ffmpeg を使用して字幕を動画に焼き込む。
    字幕焼き込み失敗時は、ロゴ+テロップのみの動画を出力パスにコピーして正常終了（フォールバック）する。
    """
    logger.info("3. Burning subtitles...")
    
    subtitle_style = (
        "FontName=Yu Gothic UI,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=1,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=30"
    )
    
    subtitle_cmd = [
        "ffmpeg",
        "-i", input_video,
        "-vf", f"subtitles=filename='{subtitle_file}':force_style='{subtitle_style}'",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-y",
        output_path
    ]
    
    try:
        subprocess.run(subtitle_cmd, check=True, capture_output=True, text=True)
        logger.info(f"✅ {design_name}プレビュー完成: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Subtitle error: {e.stderr}")
        logger.warning("字幕焼き込み失敗、ロゴ+テロップのみで続行")
        shutil.copy(input_video, output_path)
        return output_path


def create_integrated_preview_with_subtitle(
    input_video: str,
    subtitle_file: str,
    output_path: str,
    logo_height: int = 45,
    design_name: str = "統合"
) -> str:
    """
    ロゴ+テロップ+字幕の統合プレビュー
    
    手順:
    1. ロゴ+テロップを適用
    2. 字幕を焼き込み
    """
    logger.info(f"\n=== {design_name}プレビュー生成 ===")
    
    temp_dir = Path("backend/temp/integrated")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    base_video = temp_dir / "base_10s.mp4"
    logo_video = temp_dir / "with_logo.mp4"
    
    _extract_initial_segment(input_video, str(base_video), duration_sec=10.0)
    _apply_brand_logo_and_telop(str(base_video), str(logo_video), logo_height, telop_duration=10.0)
    return _burn_subtitles_to_video(str(logo_video), subtitle_file, output_path, design_name)


def main():
    input_video = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02.mp4")
    subtitle_file = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02_whisper_semantic.srt")
    
    if Path(input_video).exists() and Path(subtitle_file).exists():
        # B案（控えめ）で統合プレビュー
        output = "backend/temp/integrated/B_with_subtitle.mp4"
        create_integrated_preview_with_subtitle(
            input_video,
            subtitle_file,
            output,
            logo_height=45,
            design_name="B案（控えめ+字幕）"
        )
        
        print(f"\n✅ 統合プレビュー: {output}")
    else:
        print("❌ Video or subtitle file not found")


if __name__ == "__main__":  # pragma: no cover
    main()
