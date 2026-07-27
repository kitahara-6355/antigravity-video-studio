import json
import uuid
from pathlib import Path
from PIL import Image, ImageDraw

def generate_fallback_thumbnail(output_path: str, width: int = 1280, height: int = 720, text: str = "Timeout Fallback"):
    """
    Pillowを使用して、アトミックに指定の解像度とテキストでサムネイル画像を生成する。
    """
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write)
    temp_path = out_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        image = Image.new("RGB", (width, height), color=(180, 50, 50))
        draw = ImageDraw.Draw(image)
        draw.text((50, 50), text, fill=(255, 255, 255))
        image.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if out_path.exists():
            out_path.unlink()
        temp_path.rename(out_path)
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        raise RuntimeError(f"Failed to generate fallback thumbnail atomically: {e}")
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        
    return out_path

def validate_thumbnail_quality(file_path: str) -> dict:
    """
    生成されたフォールバックサムネイル画像の品質要件を検証する。
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 画像破損・フォーマットの検証 (verify)
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, SyntaxError, ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"Image is corrupted or invalid format (verify): {e}")
        
    # ピクセルデータのロード検証 (load)
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (OSError, SyntaxError, ValueError, TypeError, AttributeError) as e:
        raise ValueError(f"Image is corrupted or invalid format (load): {e}")
        
    # 解像度およびアスペクト比の検証
    _validate_dimensions(width, height)
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

def _validate_dimensions(width: int, height: int) -> None:
    """
    解像度とアスペクト比を検証するヘルパー関数。
    """
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")

async def resolve_timeout_fallback_task(task_id: str) -> str:
    """
    StageBoundAgent から呼び出し可能な非同期タスク処理ハンドラ。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    output_dir = Path("backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}_fallback.png"
    
    try:
        # フォールバック画像の生成
        generate_fallback_thumbnail(
            str(output_path),
            width=1280,
            height=720,
            text=f"TIMEOUT FALLBACK\nTask: {task_id}"
        )
        
        # 品質検証
        result_info = validate_thumbnail_quality(str(output_path))
        return json.dumps(result_info)
    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Failed in resolve_timeout_fallback_task for task {task_id}: {e}")
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        raise

