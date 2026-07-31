"""
全編通してプレミアムテロップを表示（YOUTUBE_PREMIUM.mp4と同じ）
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import subprocess
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# --- 定数の定義 ---
DEFAULT_TELOP_TEXT = "デザイン書道作家 山田タロウ"
FONT_SIZE = 20
# 2026-07-25: Windows パスのみだったため CI(Ubuntu) で
# 「Failed to load any premium fonts」となっていた。候補は font_resolver に集約。
from font_resolver import candidate_paths as _font_candidate_paths

FONT_CANDIDATES = list(_font_candidate_paths(bold=True))

# 画像サイズ関連
TELOP_WIDTH = 330
TELOP_HEIGHT = 45
COMBINED_WIDTH = 358
COMBINED_HEIGHT = 45
LOGO_OFFSET_X = 28

# オーバーレイ関連
OVERLAY_POSITION = "15:15"

# デフォルトファイル名
DEFAULT_INPUT_VIDEO = "soul_narrative_REBUILT.mp4"
DEFAULT_OUTPUT_VIDEO = "soul_narrative_FINAL_PREMIUM.mp4"


def _execute_subprocess(cmd: list[str]) -> subprocess.CompletedProcess:
    """共通の外部コマンド実行関数"""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )


def _load_font_with_fallback(font_size: int) -> ImageFont:
    """高級感のあるフォントをシステムから読み込む（フォールバックあり）"""
    for font_path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            continue
    # すべて失敗した場合はOSErrorを発生させる
    raise OSError("Failed to load any premium fonts.")


def _calculate_text_center_position(
    draw,
    text: str,
    font: ImageFont,
    container_width: int,
    container_height: int
) -> tuple[int, int]:
    """テキストをコンテナ中央に配置するための描画座標 (x, y) を計算する"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = (container_width - text_width) // 2
    text_y = (container_height - text_height) // 2
    return text_x, text_y


def _generate_telop_image(text: str, font: ImageFont, width: int = TELOP_WIDTH, height: int = TELOP_HEIGHT) -> Image.Image:
    """テロップのテキストを描画したRGBA画像を生成する"""
    image = Image.new('RGBA', (width, height), (0, 0, 0, 128))
    draw = ImageDraw.Draw(image)
    
    text_x, text_y = _calculate_text_center_position(draw, text, font, width, height)
    
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))
    return image


def _combine_logo_and_telop(
    logo_image: Image.Image,
    telop_image: Image.Image,
    width: int = COMBINED_WIDTH,
    height: int = COMBINED_HEIGHT,
    offset_x: int = LOGO_OFFSET_X
) -> Image.Image:
    """ロゴ画像とテロップ画像を結合する"""
    combined = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    combined.paste(logo_image, (0, 0), logo_image)
    combined.paste(telop_image, (offset_x, 0), telop_image)
    return combined


def _resolve_branding_paths(project_root: Path) -> tuple[Path, Path]:
    """ロゴとプレミアムブランディング画像の出力パスを取得する"""
    logo_path = project_root / "backend" / "branding" / "logos" / "brand_logo.png"
    output_path = _writable_path("backend/branding/premium_branding.png")
    return logo_path, output_path


def _load_logo_image(logo_path: Path) -> Image.Image:
    """ロゴファイルが存在するか確認し、RGBA画像として読み込む"""
    if not logo_path.exists():
        raise FileNotFoundError(f"Logo file not found: {logo_path}")
    return Image.open(logo_path).convert('RGBA')


def _build_premium_image(logo_image: Image.Image, text: str) -> Image.Image:
    """ロゴとプレミアムフォントのテロップを結合したRGBA画像を生成する"""
    font = _load_font_with_fallback(FONT_SIZE)
    telop_image = _generate_telop_image(text, font)
    return _combine_logo_and_telop(logo_image, telop_image)


def create_premium_branding() -> Path:
    """ロゴ + プレミアムフォント of テロップを作成（YOUTUBE_PREMIUM.mp4と同じ）"""
    project_root = Path(__file__).resolve().parent.parent
    logo_path, output_path = _resolve_branding_paths(project_root)
    
    logo_image = _load_logo_image(logo_path)
    branding_combined_image = _build_premium_image(logo_image, DEFAULT_TELOP_TEXT)
    branding_combined_image.save(output_path)
    
    print(f"✅ Premium branding created: {output_path}")
    print(f"   Font: Yu Gothic Bold {FONT_SIZE}px")
    return output_path


def _rebuild_video_from_segments(input_video: Path, concat_list: Path) -> bool:
    """セグメントから動画を再構築する"""
    print("Rebuilding from segments first...")
    
    ffmpeg_concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(input_video)
    ]
    
    try:
        result = _execute_subprocess(ffmpeg_concat_cmd)
        if result.returncode != 0:
            print("❌ Failed to rebuild from segments")
            return False
        return True
    except FileNotFoundError:
        print("❌ ffmpeg command not found. Please install ffmpeg.")
        return False
    except subprocess.SubprocessError as e:
        print(f"❌ Subprocess error during rebuild: {e}")
        return False


def _get_file_size_mb(path: Path) -> float:
    """指定されたパスのファイルサイズ（MB）を取得する"""
    return path.stat().st_size / 1024 / 1024


def _get_video_duration(video_path: Path) -> float:
    """動画の再生時間（秒）を取得する"""
    ffprobe_duration_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    duration_result = _execute_subprocess(ffprobe_duration_cmd)
    if duration_result.returncode != 0:
        raise subprocess.SubprocessError(f"ffprobe failed with returncode {duration_result.returncode}")
    return float(duration_result.stdout.strip())


def _verify_and_prepare_input_video(input_video: Path, project_root: Path) -> bool:
    """入力動画の存在を保証し、存在しない場合は再構築する"""
    if input_video.exists():
        return True
        
    segment_dir = project_root / "backend" / "temp" / "trimmed_segments"
    concat_list = segment_dir / "concat.txt"
    
    # ガード処理: concat.txt が存在しない場合は早期に終了
    if not concat_list.exists():
        print(f"❌ Concat list not found: {concat_list}")
        return False
        
    if not _rebuild_video_from_segments(input_video, concat_list):
        return False
        
    # stat が失敗した場合は例外が伝播する元の挙動を維持
    size_mb = _get_file_size_mb(input_video)
    print(f"✅ Rebuilt: {size_mb:.1f} MB")
    return True


def _overlay_branding_image(input_video: Path, branding_path: Path, output_video: Path) -> subprocess.CompletedProcess | None:
    """FFmpegを実行してブランディング画像を動画にオーバーレイ適用する"""
    ffmpeg_overlay_cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-i", str(branding_path),
        "-filter_complex", f"[0:v][1:v] overlay={OVERLAY_POSITION}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_video)
    ]
    
    try:
        return _execute_subprocess(ffmpeg_overlay_cmd)
    except FileNotFoundError:
        print("❌ ffmpeg command not found. Please install ffmpeg.")
        return None
    except subprocess.SubprocessError as e:
        print(f"❌ Subprocess error during overlay: {e}")
        return None


def _convert_seconds_to_minutes_and_seconds(duration_sec: float) -> tuple[int, int]:
    """動画の秒数から分と残りの秒数を計算して返す"""
    duration_min = int(duration_sec // 60)
    duration_sec_remaining = int(duration_sec % 60)
    return duration_min, duration_sec_remaining


def _get_video_metadata_summary(video_path: Path) -> dict:
    """動画ファイルからサイズ(MB)および再生時間(秒)を取得する"""
    size_mb = _get_file_size_mb(video_path)
    try:
        duration_sec = _get_video_duration(video_path)
    except FileNotFoundError as e:
        raise FileNotFoundError("ffprobe command not found. Please install ffmpeg.") from e
    except (ValueError, subprocess.SubprocessError) as e:
        raise subprocess.SubprocessError(f"Failed to parse video duration: {e}") from e
    return {
        "size_mb": size_mb,
        "duration_sec": duration_sec
    }


def _display_final_summary(output_video: Path) -> bool:
    """完了時の動画情報（サイズ、再生時間など）を出力する"""
    try:
        metadata = _get_video_metadata_summary(output_video)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return False
    except subprocess.SubprocessError as e:
        print(f"❌ {e}")
        return False

    duration_min, duration_sec_remaining = _convert_seconds_to_minutes_and_seconds(metadata["duration_sec"])
    print(f"\n✅ Final premium video complete!")
    print(f"   File: {output_video}")
    print(f"   Size: {metadata['size_mb']:.1f} MB")
    print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
    print(f"   Telop: 全編通して表示")
    print(f"   Font: Yu Gothic Bold {FONT_SIZE}px")
    return True


def _print_header() -> None:
    """処理開始ヘッダーを出力する"""
    print("\n" + "="*70)
    print("Adding Premium Telop to ENTIRE Video")
    print("="*70)


def _handle_overlay_failure(result: subprocess.CompletedProcess) -> None:
    """オーバーレイ処理失敗時のエラーメッセージをコンソールに出力する"""
    print(f"\n❌ Failed to add premium telop")
    print(result.stderr[-1000:] if result.stderr else "")


def _run_overlay_and_finalize(input_video: Path, branding_path: Path, output_video: Path) -> str | None:
    """FFmpegオーバーレイを適用して結果のサマリーを表示する"""
    _print_header()
    
    # 全編通してオーバーレイ（enable条件なし = 常に表示）
    result = _overlay_branding_image(input_video, branding_path, output_video)
    if result is None:
        return None
    
    if result.returncode == 0 and output_video.exists():
        if not _display_final_summary(output_video):
            return None
        return str(output_video)
    
    _handle_overlay_failure(result)
    return None


def apply_premium_telop_to_entire_video() -> str | None:
    """全編通してプレミアムテロップを表示"""
    project_root = Path(__file__).resolve().parent.parent
    input_video = project_root / DEFAULT_INPUT_VIDEO
    output_video = project_root / DEFAULT_OUTPUT_VIDEO
    
    # 入力ファイルが存在しない場合、セグメントから再構築
    if not _verify_and_prepare_input_video(input_video, project_root):
        return None
    
    branding_path = create_premium_branding()
    
    return _run_overlay_and_finalize(input_video, branding_path, output_video)


def main():
    """エントリーポイント"""
    start = time.time()
    
    video_path = apply_premium_telop_to_entire_video()
    
    elapsed = time.time() - start
    
    print("\n" + "="*70)
    print(f"Processing complete: {elapsed / 60:.1f} minutes")
    print("="*70)
    
    if video_path:
        print("\n🚀 Premium Video Ready for YouTube!")
        print(f"   {video_path}")
    else:
        print("\n❌ Failed")


if __name__ == "__main__":
    main()
