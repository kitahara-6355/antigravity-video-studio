try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from branding_manager import branding_manager
from branding.history_manager import history_manager

print("Testing BrandingManager...")
try:
    branding_manager.update_user_rank("tech_rank", 5)
    print("Rank updated successfully.")
    
    history = history_manager.get_history(1)
    if history and history[0]['type'] == 'STATUS_CHANGE':
        print(f"History verification successful: {history[0]}")
    else:
        print("History verification FAILED/Empty.")
except (ValueError, AttributeError, KeyError) as e:
    print(f"Error: {e}")

# --- サムネイル画像処理・品質検証・StageBoundAgent連携ロジックの追加 ---
import json
from pathlib import Path
from PIL import Image, ImageDraw, UnidentifiedImageError
from usage_tracker.alert_system import emit_warning, emit_critical

class ThumbnailQualityVerifier:
    @staticmethod
    def validate(file_path: str) -> dict:
        """
        品質基準の検証:
        - 生成画像の解像度が 1280x720 以上であること
        - アスペクト比が 16:9 であること
        - ファイルサイズが 4MB 未満であること
        - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
        """
        path = Path(file_path)
        if not path.exists():
            msg = f"Thumbnail file not found: {path}"
            emit_warning("thumbnail", msg)
            raise FileNotFoundError(msg)

        size_bytes = path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            msg = f"File size exceeds 4MB limit: {size_bytes} bytes"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        try:
            with Image.open(path) as img:
                img.verify()
        except (UnidentifiedImageError, OSError) as e:
            msg = f"Image is corrupted or invalid format: {e}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        try:
            with Image.open(path) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError) as e:
            msg = f"Failed to load image for resolution check: {e}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        if width < 1280 or height < 720:
            msg = f"Resolution must be at least 1280x720. Got {width}x{height}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 1e-3:
            msg = f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        return {
            "path": str(path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

def generate_thumbnail_file(output_path: str, width: int = 1280, height: int = 720, text: str = "Thumbnail") -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(255, 255, 0))
    img.save(path, "PNG")
    return path

async def resolve_thumbnail_task(task_id: str, db_path: str = ":memory:", output_dir: str = str(_writable_path("temp_thumbnails"))) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理。
    """
    try:
        output_path = Path(output_dir) / f"{task_id}.png"
        generate_thumbnail_file(str(output_path))
        result_info = ThumbnailQualityVerifier.validate(str(output_path))
        return json.dumps(result_info)
    except (FileNotFoundError, ValueError, OSError) as e:
        emit_critical("thumbnail", f"Thumbnail task failed for task {task_id}: {e}")
        raise
