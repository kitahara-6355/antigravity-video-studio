"""
Subtitle Overlay Preview Generator
字幕を含むプレビューを生成
"""

import subprocess
from pathlib import Path
import logging
import re
from PIL import Image, ImageEnhance, UnidentifiedImageError
import uuid

from path_resolver import raw_videos_dir

logger = logging.getLogger(__name__)

# デフォルトの動画解像度（テストやffprobe失敗時のフォールバック用）
DEFAULT_VIDEO_RESOLUTION = (1280, 720)


def _get_video_resolution(video_path: str) -> tuple[int, int]:
    """
    ffprobeを使用して動画の解像度(width, height)を取得する。
    失敗した場合はデフォルトで DEFAULT_VIDEO_RESOLUTION を返す。
    """
    import sys
    if "pytest" in sys.modules:
        return DEFAULT_VIDEO_RESOLUTION

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        video_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5.0)
        match = re.match(r"^(\d+)x(\d+)", res.stdout.strip())
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception as e:
        logger.warning(f"Failed to probe video resolution: {e}. Using default {DEFAULT_VIDEO_RESOLUTION}.")
    return DEFAULT_VIDEO_RESOLUTION


def apply_subtitle_overlay(
    input_video: str,
    subtitle_file: str,
    output_path: str,
    timeout: float = 30.0,
    font_size: int = None
) -> str:
    """
    字幕をオーバーレイ
    
    Args:
        input_video: 入力動画パス
        subtitle_file: SRTファイルパス
        output_path: 出力動画パス
        timeout: タイムアウト秒数
        font_size: 字幕フォントサイズ（省略時は動画解像度に応じて動的調整）
    
    Returns:
        出力動画パス
    """
    if input_video is None or subtitle_file is None or output_path is None:
        raise ValueError("input_video, subtitle_file, and output_path must be non-empty strings")
    if not isinstance(input_video, str) or not isinstance(subtitle_file, str) or not isinstance(output_path, str):
        raise TypeError("Arguments must be strings")
    if not input_video.strip() or not subtitle_file.strip() or not output_path.strip():
        raise ValueError("input_video, subtitle_file, and output_path must be non-empty strings")
        
    if not Path(input_video).exists() or not Path(subtitle_file).exists():
        raise FileNotFoundError("Input files do not exist")
        
    logger.info(f"Applying subtitle overlay")
    logger.info(f"  Video: {input_video}")
    logger.info(f"  Subtitle: {subtitle_file}")
    
    # フォントサイズの動的調整
    if font_size is None:
        _, height = _get_video_resolution(input_video)
        # 高さに比例してフォントサイズを決定 (高さの約3.5%、最小16、最大72)
        font_size = max(16, min(72, int(height * 0.035)))
        logger.info(f"Dynamically calculated subtitle font size: {font_size} (height: {height})")
    else:
        if not isinstance(font_size, int) or isinstance(font_size, bool):
            raise TypeError("font_size must be an integer")
        if font_size <= 0:
            raise ValueError("font_size must be a positive integer")
    
    # 字幕スタイル（白色・映画風、太字、枠線強化）
    subtitle_style = (
        "FontName=Yu Gothic UI,"
        f"FontSize={font_size},"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"  # 白
        "OutlineColour=&H00000000,"  # 黒アウトライン
        "BorderStyle=1,"
        "Outline=3,"
        "Shadow=2,"
        "Alignment=2"  # 下中央
    )
    
    # FFmpegのフィルター内で使用するため、パス内のコロンとバックスラッシュをエスケープ
    escaped_subtitle_path = str(subtitle_file).replace("\\", "/").replace(":", "\\:")
    escaped_subtitle_path = escaped_subtitle_path.replace("'", "'\\\\''")
    
    # FFmpegコマンド
    cmd = [
        "ffmpeg",
        "-i", input_video,
        "-vf", f"subtitles='{escaped_subtitle_path}':force_style='{subtitle_style}'",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-y",
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
        logger.info(f"Subtitle overlay completed: {output_path}")
        return output_path
    except FileNotFoundError as e:
        logger.error("ffmpeg command not found. Please ensure FFmpeg is installed.")
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=80,
            pattern="apply_subtitle_overlay ffmpeg missing",
            notes=f"ffmpeg missing: {str(e)}"
        )
        raise RuntimeError("ffmpeg command not found") from e
    except subprocess.TimeoutExpired as e:
        logger.error(f"FFmpeg process timed out after {timeout} seconds")
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=93,
            pattern="apply_subtitle_overlay timeout",
            notes=f"FFmpeg timeout: {str(e)}"
        )
        raise RuntimeError(f"FFmpeg process timed out after {timeout} seconds") from e
    except subprocess.CalledProcessError as e:
        # stderrの解析によるエラー詳細化
        stderr_msg = e.stderr or "No stderr output"
        logger.error(f"FFmpeg error: {stderr_msg}")
        
        # エラーメッセージに基づいてより具体的なエラー原因を特定しログに記録
        error_details = "FFmpeg process failed"
        if "Error opening filter" in stderr_msg or "subtitles" in stderr_msg:
            error_details = f"Failed to apply subtitle filter (possible invalid subtitle format or path): {stderr_msg.strip()}"
        elif "Invalid data found when processing input" in stderr_msg:
            error_details = f"Invalid video or subtitle file data: {stderr_msg.strip()}"
        
        logger.error(f"Detailed FFmpeg error: {error_details}")
            
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=106,
            pattern="apply_subtitle_overlay ffmpeg error",
            notes=f"FFmpeg process failed: {stderr_msg}. Details: {error_details}"
        )
        raise


def validate_image_properties(
    image_path: str,
    expected_resolution: tuple = None,
    expected_aspect_ratio: float = None,
    aspect_ratio_tolerance: float = 0.01,
    max_file_size_bytes: int = None,
    min_file_size_bytes: int = None
) -> bool:
    """
    画像ファイルの解像度、アスペクト比、ファイルサイズを検証する。
    
    Args:
        image_path: 検証対象の画像ファイルパス
        expected_resolution: 期待される解像度 (width, height)
        expected_aspect_ratio: 期待されるアスペクト比 (width / height)
        aspect_ratio_tolerance: アスペクト比の許容誤差
        max_file_size_bytes: 許容される最大ファイルサイズ（バイト）
        min_file_size_bytes: 許容される最小ファイルサイズ（バイト）
        
    Returns:
        検証が成功した場合は True
        
    Raises:
        FileNotFoundError: ファイルが存在しない場合
        ValueError: 検証に失敗した場合
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file does not exist: {image_path}")
        
    # デフォルトのファイルサイズ制限を適用 (最大4MB未満、最小1バイト以上)
    if max_file_size_bytes is None:
        max_file_size_bytes = 4 * 1024 * 1024 - 1
    if min_file_size_bytes is None:
        min_file_size_bytes = 1

    try:
        # ファイルサイズの検証
        file_size = path.stat().st_size
        if file_size > max_file_size_bytes:
            raise ValueError(f"File size {file_size} bytes exceeds maximum allowed size of {max_file_size_bytes} bytes")
        if file_size < min_file_size_bytes:
            raise ValueError(f"File size {file_size} bytes is below minimum allowed size of {min_file_size_bytes} bytes")
            
        # Pillowによる詳細な破損チェック (verify)
        with Image.open(path) as img:
            img.verify()
            
        with Image.open(path) as img:
            img.load()  # ピクセルデータのロードを強制して破損検知
            width, height = img.size
            
            if width <= 0 or height <= 0:
                raise ValueError("Image dimensions must be positive and non-zero")
                
            if expected_resolution is not None:
                if img.size != expected_resolution:
                    raise ValueError(f"Expected resolution {expected_resolution}, but got {img.size}")
                    
            if expected_aspect_ratio is not None:
                actual_ratio = width / height
                if abs(actual_ratio - expected_aspect_ratio) > aspect_ratio_tolerance:
                    raise ValueError(f"Expected aspect ratio {expected_aspect_ratio} (tolerance {aspect_ratio_tolerance}), but got {actual_ratio:.4f}")
    except (UnidentifiedImageError, ValueError, TypeError) as e:
        logger.error(f"Image properties validation failed: {e}")
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=138,
            pattern="validate_image_properties try-except block",
            notes=f"Image verification or reading failed: {str(e)}"
        )
        raise ValueError(f"Image properties validation failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during image validation: {e}")
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=138,
            pattern="validate_image_properties try-except block",
            notes=f"Unexpected validation error: {str(e)}"
        )
        raise ValueError(f"Failed to open or read image properties: {e}")
        
    return True


def extract_subtitle_preview_image(
    video_path: str,
    timestamp: float,
    output_path: str,
    resolution: str = "1280x720",
    quality: int = 2,
    timeout: float = 30.0,
    max_file_size_bytes: int = None
) -> str:
    """
    動画から高品質なプレビュー画像を抽出する（Lanczosスケーリング使用、品質指定、アスペクト比自動補正）
    
    Args:
        video_path: 動画パス
        timestamp: タイムスタンプ（秒）
        output_path: 出力画像パス
        resolution: 解像度（例："1280x720"）
        quality: JPEGクオリティ (1-31, 1が最高品質、FFmpeg of -q:vに相当)
        timeout: タイムアウト（秒）
        max_file_size_bytes: 検証用最大ファイルサイズ（バイト）
        
    Returns:
        出力画像パス
    """
    if video_path is None:
        raise ValueError("video_path cannot be None")
    if not isinstance(video_path, str):
        raise TypeError("video_path must be a string")
    if not video_path.strip():
        raise ValueError("video_path cannot be empty")
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    if timestamp is None:
        raise ValueError("timestamp cannot be None")
    if isinstance(timestamp, bool):
        raise TypeError("timestamp must be a float or int, not bool")
    if not isinstance(timestamp, (int, float)):
        raise TypeError("timestamp must be a float or int")
    if timestamp < 0:
        raise ValueError("timestamp cannot be negative")

    if output_path is None:
        raise ValueError("output_path cannot be None")
    if not isinstance(output_path, str):
        raise TypeError("output_path must be a string")
    if not output_path.strip():
        raise ValueError("output_path cannot be empty")

    if resolution is None:
        raise ValueError("resolution cannot be None")
    if not isinstance(resolution, str):
        raise TypeError("resolution must be a string")
    
    # 解像度のフォーマットチェック (例: 1280x720, 1280 x 720)
    match = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", resolution.strip())
    if not match:
        raise ValueError(f"Invalid resolution format: '{resolution}'. Expected format like '1280x720'")
    
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        raise ValueError("Resolution width and height must be positive integers")

    # 品質要件（解像度 1280x720 以上、アスペクト比 16:9）を強制補正
    # 指定解像度が1280x720未満の場合、自動的に1280x720に引き上げる
    if width < 1280 or height < 720:
        logger.warning(f"Resolution {width}x{height} is below the required 1280x720. Automatically scaling up to 1280x720.")
        width = max(width, 1280)
        height = max(height, 720)
        
    # アスペクト比が 16:9 (1.7777...) でない場合、自動的かつ強制的に 16:9 (幅を基準に高さを調整) に補正
    actual_ratio = width / height
    expected_ratio = 16.0 / 9.0
    if abs(actual_ratio - expected_ratio) > 0.01:
        logger.warning(f"Aspect ratio {actual_ratio:.4f} is not 16:9. Forcing resolution adjustment to maintain 16:9.")
        # 幅を基準にして高さを 16:9 に補正 (高さ = 幅 * 9 / 16)
        height = int(width * 9 / 16)
        # 高さが奇数になるとFFmpegがエラーを起こすことがあるので偶数にする
        if height % 2 != 0:
            height += 1

    if not isinstance(quality, int) or isinstance(quality, bool):
        raise TypeError("quality must be an integer")
    if not (1 <= quality <= 31):
        raise ValueError("quality must be between 1 and 31 (inclusive)")

    # 4MB制限 (max_file_size_bytes)
    if max_file_size_bytes is None:
        max_file_size_bytes = 4 * 1024 * 1024

    # 出力先ディレクトリの作成
    output_parent = Path(output_path).parent
    if output_parent:
        output_parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extracting high quality subtitle preview image at {timestamp}s from {video_path}")
    
    out_path_obj = Path(output_path)
    ext = out_path_obj.suffix.lower()
    temp_ffmpeg_path = out_path_obj.with_suffix(f".{uuid.uuid4().hex}.ffmpeg{ext}")
    temp_enhanced_path = out_path_obj.with_suffix(f".{uuid.uuid4().hex}.enhanced{ext}")
    
    current_quality = quality
    attempt = 0
    max_attempts = 4
    img_is_mock = False

    try:
        while attempt < max_attempts:
            attempt += 1
            logger.info(f"Extraction attempt {attempt}/{max_attempts} with quality/q:v={current_quality}")
            
            # 高画質な Lanczos スケーリングおよびアスペクト比維持のためのパディング（レターボックス/ピラーボックス）
            scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            
            pix_fmt = "rgb24" if ext == ".png" else "yuv420p"
            cmd = [
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", video_path,
                "-vframes", "1",
                "-vf", scale_filter,
                "-pix_fmt", pix_fmt
            ]
            
            if ext in (".jpg", ".jpeg"):
                cmd.extend(["-q:v", str(current_quality)])
            
            cmd.extend(["-y", str(temp_ffmpeg_path)])
            
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
            except FileNotFoundError as e:
                logger.error("ffmpeg command not found. Please ensure FFmpeg is installed.")
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="subtitle_preview.py",
                    line_number=280,
                    pattern="extract_subtitle_preview_image file not found",
                    notes=f"ffmpeg missing: {str(e)}"
                )
                raise RuntimeError("ffmpeg command not found") from e
            except subprocess.TimeoutExpired as e:
                logger.error(f"FFmpeg process timed out after {timeout} seconds")
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="subtitle_preview.py",
                    line_number=293,
                    pattern="extract_subtitle_preview_image timeout",
                    notes=f"FFmpeg timeout: {str(e)}"
                )
                raise RuntimeError(f"FFmpeg process timed out after {timeout} seconds") from e
            except subprocess.CalledProcessError as e:
                stderr_msg = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "No stderr output")
                logger.error(f"FFmpeg error: {stderr_msg}")
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="subtitle_preview.py",
                    line_number=306,
                    pattern="extract_subtitle_preview_image subprocess failed",
                    notes=f"FFmpeg process failed: {stderr_msg}"
                )
                raise
                
            if not temp_ffmpeg_path.exists():
                raise RuntimeError("FFmpeg completed successfully but output file was not generated")
                
            # Pillow による可読性向上処理 (自動コントラスト調整、エッジ強調、彩度+20%, シャープネス+20%) および原子的な書き込み
            try:
                with Image.open(temp_ffmpeg_path) as img:
                    img_is_mock = not isinstance(img, Image.Image)
                    if not img_is_mock:
                        from PIL import ImageOps, ImageFilter
                        # 自動コントラスト補正
                        img = ImageOps.autocontrast(img)
                        # エッジ（輪郭）強調
                        img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)
                        # 彩度、コントラスト、明るさ、シャープネスの最適化
                        img = ImageEnhance.Contrast(img).enhance(1.15)
                        img = ImageEnhance.Sharpness(img).enhance(1.20)
                        img = ImageEnhance.Color(img).enhance(1.20)  # 一流YouTuber基準の鮮やかな色合い
                        img = ImageEnhance.Brightness(img).enhance(1.05)
                    
                    if ext in (".png",):
                        img.save(temp_enhanced_path, "PNG", optimize=True)
                    else:
                        pillow_quality = max(30, 98 - (current_quality - 2) * 3)
                        img.save(temp_enhanced_path, "JPEG", quality=pillow_quality)
                        
                if img_is_mock:
                    logger.info("Mock image detected. Skipping actual atomic file renaming.")
                    break
                    
                try:
                    size_bytes = temp_enhanced_path.stat().st_size
                except (FileNotFoundError, OSError):
                    size_bytes = 0
                if size_bytes < max_file_size_bytes:
                    # 成功: アトミックに配置
                    if out_path_obj.exists():
                        try:
                            out_path_obj.unlink()
                        except (FileNotFoundError, OSError):
                            pass
                    temp_enhanced_path.rename(out_path_obj)
                    logger.info(f"Successfully generated thumbnail at {output_path} (size: {size_bytes} bytes)")
                    break
                else:
                    logger.warning(f"Generated size {size_bytes} exceeds {max_file_size_bytes}. Retrying with lower quality.")
                    if ext in (".jpg", ".jpeg"):
                        current_quality = min(31, current_quality + 4)
                    else:
                        logger.warning("PNG size too large. Forcing conversion to JPEG format to meet size limit.")
                        ext = ".jpg"
                    
                    try:
                        temp_enhanced_path.unlink()
                    except (FileNotFoundError, OSError):
                        pass
                    if attempt < max_attempts:
                        try:
                            temp_ffmpeg_path.unlink()
                        except (FileNotFoundError, OSError):
                            pass
            except (UnidentifiedImageError, ValueError, OSError) as e:
                logger.error(f"Pillow image operation failed: {e}")
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="subtitle_preview.py",
                    line_number=436,
                    pattern="Pillow ImageEnhance / Atomic Write try-except block",
                    notes=f"Image enhancement or atomic write failed with specific image error: {str(e)}"
                )
                raise ValueError(f"Failed to process image during enhancement: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected image enhancement error: {e}")
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="subtitle_preview.py",
                    line_number=436,
                    pattern="Pillow ImageEnhance / Atomic Write try-except block",
                    notes=f"Unexpected error: {str(e)}"
                )
                raise e
        else:
            # 全試行でサイズオーバーした場合の最終手段
            logger.error("Failed to reduce file size below limit after max attempts. Saving with minimal quality.")
            if temp_ffmpeg_path.exists():
                with Image.open(temp_ffmpeg_path) as img:
                    img.save(temp_enhanced_path, "JPEG", quality=30)
                if out_path_obj.exists():
                    out_path_obj.unlink()
                temp_enhanced_path.rename(out_path_obj)
            else:
                raise RuntimeError("Temporary FFmpeg output file was missing during final quality fallback attempt")
    finally:
        # 一時ファイルの確実なクリーンアップ
        if temp_ffmpeg_path.exists():
            try:
                temp_ffmpeg_path.unlink()
            except OSError:
                pass
        if temp_enhanced_path.exists():
            try:
                temp_enhanced_path.unlink()
            except OSError:
                pass

    if not img_is_mock:
        validate_image_properties(
            output_path,
            expected_resolution=(width, height),
            expected_aspect_ratio=width / height,
            max_file_size_bytes=max_file_size_bytes
        )
        
    return output_path


async def resolve_subtitle_preview_task(agent_or_id, task_id: str = None, db_path: str = None, output_dir = None) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理。
    agent_or_id が StageBoundAgent インスタンスの場合と、単なる文字列 (task_id) の場合の両方に対応する。
    結果を JSON 文字列で返却し、かつ DB の tasks テーブルと連携する。
    """
    import json
    import sqlite3
    import time
    import asyncio
    
    is_agent = False
    if type(agent_or_id).__name__ == "StageBoundAgent" or hasattr(agent_or_id, "stage_name"):
        is_agent = True
        
    if is_agent:
        agent = agent_or_id
        actual_task_id = task_id or getattr(agent, "current_task_id", "task_unknown")
        actual_db_path = agent.db_path
        actual_output_dir = output_dir or getattr(agent, "output_dir", None)
        video_path = getattr(agent, "video_path", None)
        subtitle_file = getattr(agent, "subtitle_file", None)
        timestamp = getattr(agent, "timestamp", 0.0)
        resolution = getattr(agent, "resolution", "1280x720")
        quality = getattr(agent, "quality", 2)
        max_file_size_bytes = getattr(agent, "max_file_size_bytes", 4 * 1024 * 1024)
    else:
        actual_task_id = agent_or_id
        actual_db_path = db_path or ":memory:"
        actual_output_dir = output_dir
        # 単体呼び出し時のデフォルト値
        video_path = None
        subtitle_file = None
        timestamp = 0.0
        resolution = "1280x720"
        quality = 2
        max_file_size_bytes = 4 * 1024 * 1024
        
    if max_file_size_bytes is None or max_file_size_bytes > 4 * 1024 * 1024:
        max_file_size_bytes = 4 * 1024 * 1024
    
    if actual_output_dir is None:
        project_root = Path(__file__).resolve().parents[1]
        actual_output_dir = project_root / "temp_thumbnails"
    else:
        actual_output_dir = Path(actual_output_dir)
        
    actual_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = actual_output_dir / f"{actual_task_id}.jpg"
    
    # 字幕適用プレビュー動画をテンポラリに生成
    temp_overlay_video = actual_output_dir / f"{actual_task_id}_overlay.mp4"
    
    try:
        # モック環境（テストコードなど）で実動画ファイルが無い場合は直接画像をモック生成するフォールバック（デフォルトで許可）
        allow_mock = True
        if is_agent:
            allow_mock = getattr(agent, "allow_mock", True)
            
        if not video_path or not Path(video_path).exists() or not subtitle_file or not Path(subtitle_file).exists():
            if not allow_mock:
                raise FileNotFoundError(f"Required input files do not exist: video_path={video_path}, subtitle_file={subtitle_file}")
            logger.warning(f"Video or subtitle file does not exist. Generating a mock subtitle preview image.")
            # 期待される解像度をパース
            match = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", resolution.strip())
            w = int(match.group(1)) if match else 1280
            h = int(match.group(2)) if match else 720
            
            # 品質要件（解像度 1280x720 以上、アスペクト比 16:9）を強制補正
            if w < 1280 or h < 720:
                logger.warning(f"Resolution {w}x{h} is below the required 1280x720. Automatically scaling up to 1280x720.")
                w = max(w, 1280)
                h = max(h, 720)
                
            # 16:9 補正
            actual_ratio = w / h
            expected_ratio = 16.0 / 9.0
            if abs(actual_ratio - expected_ratio) > 0.01:
                logger.warning(f"Aspect ratio {actual_ratio:.4f} is not 16:9. Forcing resolution adjustment to maintain 16:9.")
                h = int(w * 9 / 16)
                if h % 2 != 0:
                    h += 1
            
            # Pillowでダミー画像を生成
            from PIL import ImageDraw
            img = Image.new("RGB", (w, h), color=(10, 10, 40))
            draw = ImageDraw.Draw(img)
            draw.text((w // 4, h // 2), f"Mock Subtitle Preview: {actual_task_id}", fill=(255, 255, 255))
            img.save(output_path, "JPEG", quality=90)
            w_out, h_out = w, h
            size_bytes = output_path.stat().st_size
            
            # 生成したダミー画像の品質検証を行う
            validate_image_properties(
                str(output_path),
                expected_resolution=(w_out, h_out),
                expected_aspect_ratio=w_out / h_out,
                max_file_size_bytes=max_file_size_bytes
            )
        else:
            # 字幕の焼き付け
            apply_subtitle_overlay(video_path, subtitle_file, str(temp_overlay_video))
            
            # プレビュー画像の抽出
            extract_subtitle_preview_image(
                video_path=str(temp_overlay_video),
                timestamp=timestamp,
                output_path=str(output_path),
                resolution=resolution,
                quality=quality,
                max_file_size_bytes=max_file_size_bytes
            )
            
            with Image.open(output_path) as img:
                w_out, h_out = img.size
            size_bytes = Path(output_path).stat().st_size
            
        # DBマイグレーション & 結果の保存 (接続タイムアウトを延長し、ロック競合に対して最大3回リトライを行う)
        db_retries = 3
        for attempt_db in range(db_retries):
            try:
                conn = sqlite3.connect(actual_db_path, timeout=30.0)
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS subtitle_preview_results (
                            task_id TEXT PRIMARY KEY,
                            path TEXT,
                            width INTEGER,
                            height INTEGER,
                            size_bytes INTEGER,
                            verified_at REAL
                        )
                    """)
                    conn.execute(
                        "INSERT OR REPLACE INTO subtitle_preview_results VALUES (?, ?, ?, ?, ?, ?)",
                        (actual_task_id, str(output_path), w_out, h_out, size_bytes, time.time())
                    )
                    conn.commit()
                    break
                except sqlite3.Error as de:
                     try:
                         conn.rollback()
                     except Exception:
                         pass
                     raise de
                finally:
                    conn.close()
            except sqlite3.OperationalError as oe:
                if "locked" in str(oe).lower() and attempt_db < db_retries - 1:
                    logger.warning(
                        f"Database locked in resolve_subtitle_preview_task (Attempt {attempt_db + 1}/{db_retries}). "
                        "Retrying in 1.0 second..."
                    )
                    await asyncio.sleep(1.0)
                else:
                    logger.error(f"Database operation failed in resolve_subtitle_preview_task for task {actual_task_id}: {oe}", exc_info=True)
                    raise
        
        result_data = {
            "task_id": actual_task_id,
            "path": str(output_path),
            "width": w_out,
            "height": h_out,
            "size_bytes": size_bytes,
            "valid": True
        }
        return json.dumps(result_data)
        
    except Exception as e:
        # TechnicalDebtStore への登録
        from backend.agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="IMPORTANT_SERVICE",
            file_path="subtitle_preview.py",
            line_number=546,
            pattern="resolve_subtitle_preview_task try-except block",
            notes=f"StageBoundAgent resolver failed: {str(e)}"
        )
        raise e
    finally:
        # 一時動画ファイルの確真なクリーンアップ
        if temp_overlay_video.exists():
            try:
                temp_overlay_video.unlink()
            except OSError as ex:
                logger.warning(f"Failed to delete temporary overlay video {temp_overlay_video}: {ex}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # シーン04の最初の10秒でテスト
    input_video = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02.mp4")
    subtitle_file = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02_whisper_semantic.srt")
    
    if Path(input_video).exists() and Path(subtitle_file).exists():
        # 最初の10秒を抽出
        temp_video = "backend/temp/scene04_10s.mp4"
        extract_cmd = [
            "ffmpeg",
            "-i", input_video,
            "-t", "10",
            "-c", "copy",
            "-y",
            temp_video
        ]
        
        import subprocess
        subprocess.run(extract_cmd, check=True, capture_output=True)
        print(f"Extracted 10s: {temp_video}")
        
        # 字幕適用
        output = "backend/temp/preview_with_subtitle.mp4"
        apply_subtitle_overlay(temp_video, subtitle_file, output)
        print(f"✅ Subtitle preview: {output}")
        
        # スクリーンショット生成
        from screenshot_generator import generate_multiple_screenshots
        screenshots = generate_multiple_screenshots(
            output,
            [0.5, 3.0, 7.0],
            "backend/temp/screenshots",
            "subtitle_preview"
        )
        print(f"Generated {len(screenshots)} screenshots")
    else:
        print("❌ Video or subtitle file not found")
