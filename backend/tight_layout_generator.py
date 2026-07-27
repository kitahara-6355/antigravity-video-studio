"""
Logo and Telop Tight Layout Generator
ロゴとテロップを密着配置
"""

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys
import io
import logging
from typing import Optional

logger = logging.getLogger("tight_layout_generator")


def _run_ffmpeg_command(cmd: list, step_name: str) -> subprocess.CompletedProcess:
    """FFmpegコマンドを実行し、詳細なロギングとエラーハンドリングを行う"""
    logger.info(f"Running FFmpeg: {step_name}")
    logger.debug(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        logger.info(f"FFmpeg {step_name} completed successfully")
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg {step_name} failed with exit code {e.returncode}")
        logger.error(f"FFmpeg Command: {' '.join(e.cmd)}")
        logger.error(f"FFmpeg Stdout: {e.stdout}")
        logger.error(f"FFmpeg Stderr: {e.stderr}")
        raise
    except FileNotFoundError as e:
        logger.error(f"ffmpeg executable not found in system PATH: {e}")
        raise


def create_tight_layout_preview(
    input_video: Optional[str] = None,
    logo_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    temp_dir: Optional[str] = None,
    theme_text: str = "デザイン書道作家 山田タロウ",
    logo_height: int = 45,
) -> str:
    """
    ロゴとテロップを密着させたプレビュー生成
    """
    logger.info("密着レイアウト版プレビュー生成を開始します")
    
    # 動的デフォルト値の設定
    if not temp_dir:
        temp_dir = Path("backend/temp/tight_layout")
    else:
        temp_dir = Path(temp_dir)
        
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # 入力ビデオ
    if not input_video:
        input_video = r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン04_後編02.mp4"
    
    input_video_path = Path(input_video)
    if not input_video_path.exists():
        logger.error(f"入力ビデオファイルが見つかりません: {input_video}")
        raise FileNotFoundError(f"Input video file not found: {input_video}")
        
    # ロゴパス
    if not logo_path:
        logo_path = Path("backend/branding/logos/brand_logo.png")
    else:
        logo_path = Path(logo_path)
        
    if not logo_path.exists():
        logger.error(f"ロゴ画像ファイルが見つかりません: {logo_path}")
        raise FileNotFoundError(f"Logo image file not found: {logo_path}")
        
    # 出力ディレクトリ
    if not output_dir:
        output_dir = Path("C:/Users/PC_User/.gemini/antigravity/brain/638e528a-ad1b-4885-ad73-5d9f60dc2799")
    else:
        output_dir = Path(output_dir)
        
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"出力ディレクトリの作成に失敗しました: {output_dir}, エラー: {e}")
        raise

    # Step 1: 10秒抽出
    logger.info("[1/4] 動画抽出...")
    base_video = temp_dir / "base.mp4"
    _run_ffmpeg_command([
        "ffmpeg", "-y", "-ss", "5", "-i", str(input_video_path), "-t", "10", "-c", "copy",
        str(base_video)
    ], "extract_10s")
    
    # Step 2: ロゴサイズ計算
    try:
        with Image.open(logo_path) as logo_img:
            original_width, original_height = logo_img.size
    except (OSError, ValueError) as e:
        logger.error(f"ロゴ画像の読み込みに失敗しました: {logo_path}, エラー: {e}")
        raise
        
    # 高さ45pxでのサイズ計算
    logo_width = int(original_width * (logo_height / original_height))
    logger.info(f"ロゴサイズ: {logo_width}x{logo_height}px")
    
    # Step 3: テロップ生成（ロゴの右に密着）
    logger.info("[2/4] テロップ生成...")
    
    # フォント
    font_paths = [
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    
    font = None
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 18)
                break
            except (OSError, IOError) as e:
                logger.debug(f"フォントの読み込みに失敗しました {fp}: {e}")
    
    if font is None:
        logger.warning("システムフォントが見つかりませんでした。デフォルトフォントにフォールバックします。")
        font = ImageFont.load_default()
    
    # テキストサイズ計測
    try:
        dummy = Image.new('RGBA', (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), theme_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # テロップ画像作成
        padding = 10
        telop_width = text_width + padding * 2
        telop_height = text_height + padding * 2
        
        telop_img = Image.new('RGBA', (telop_width, telop_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(telop_img)
        
        # 半透明黒背景
        draw.rectangle((0, 0, telop_width, telop_height), fill=(0, 0, 0, 128))
        
        # テキスト
        draw.text((padding, padding), theme_text, font=font, fill=(255, 255, 255, 255))
        
        telop_path = temp_dir / "telop_tight.png"
        telop_img.save(str(telop_path))
        logger.info(f"テロップ画像を生成しました: {telop_width}x{telop_height}px, パス: {telop_path}")
    except (OSError, ValueError) as e:
        logger.error(f"テロップ画像の生成に失敗しました: {e}")
        raise
    
    # Step 4: ロゴ適用
    logger.info("[3/4] ロゴ適用...")
    logo_video = temp_dir / "with_logo.mp4"
    
    # ロゴ位置（黒背景を避ける）
    logo_x = 25
    logo_y = 30
    
    _run_ffmpeg_command([
        "ffmpeg", "-y",
        "-i", str(base_video),
        "-i", str(logo_path),
        "-filter_complex",
        f"[1:v]scale=-1:{logo_height}[logo];[0:v][logo]overlay={logo_x}:{logo_y}:format=auto",
        "-c:a", "copy",
        str(logo_video)
    ], "apply_logo")
    
    # Step 5: テロップ適用（ロゴの右に密着）
    logger.info("[4/4] テロップ適用...")
    
    # テロップ位置: ロゴの右に5pxマージン
    telop_x = logo_x + logo_width + 5
    telop_y = logo_y + 2  # ロゴとほぼ同じ高さ
    
    final_video = temp_dir / "tight_layout.mp4"
    
    _run_ffmpeg_command([
        "ffmpeg", "-y",
        "-i", str(logo_video),
        "-i", str(telop_path),
        "-filter_complex",
        f"[1:v]format=rgba[t];[0:v][t]overlay={telop_x}:{telop_y}:format=auto",
        "-c:a", "copy",
        str(final_video)
    ], "apply_telop")
    
    logger.info(f"配置情報:")
    logger.info(f"  ロゴ:     ({logo_x}, {logo_y}) - {logo_width}x{logo_height}px")
    logger.info(f"  テロップ: ({telop_x}, {telop_y}) - {telop_width}x{telop_height}px")
    logger.info(f"  間隔:     5px（密着）")
    
    # Step 6: スクリーンショット
    logger.info("[5/5] スクリーンショット生成...")
    
    for i, ts in enumerate([1, 3, 7]):
        ss_path = output_dir / f"TIGHT_screenshot_{i+1}_{ts}s.png"
        try:
            _run_ffmpeg_command([
                "ffmpeg", "-y", "-ss", str(ts), "-i", str(final_video),
                "-frames:v", "1", str(ss_path)
            ], f"screenshot_{i+1}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"スクリーンショット {i+1} の生成に失敗しました (継続可能): {e}")
    
    logger.info("密着レイアウトプレビューの生成が完了しました")
    return str(final_video)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        final = create_tight_layout_preview()
        print(f"\n✅ 成功: {final}")
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
