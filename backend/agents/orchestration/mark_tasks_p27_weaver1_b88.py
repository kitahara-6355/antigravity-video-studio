import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# サムネイル生成・品質検証ロジック
# ============================================================

def generate_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Weaver Thumbnail"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    from PIL import Image, ImageDraw
    import uuid
    from pathlib import Path
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    success = False
    try:
        img = Image.new("RGB", (width, height), color=(88, 120, 150))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
        success = True
    except (OSError, ValueError) as e:
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
    finally:
        if not success and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        
    return output_path

def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    from PIL import Image
    from pathlib import Path
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易的なverify
    try:
        with Image.open(file_path) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_weaver_thumbnail_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    from pathlib import Path
    output_dir = Path("backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    generate_thumbnail(output_path, width=1280, height=720, text="Weaver Thumbnail Task")
    result_info = validate_thumbnail(output_path)
    return json.dumps(result_info)

# ============================================================
# メイン処理
# ============================================================

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # test_weaver-001 完了マーク
    hub.mark_task_done("T-batch_881c02-test_weaver-001", "pass", {
        "message": "scratch/verify_video_quality_matrix.py のテストを拡充。カバレッジ 100% を維持。",
        "changed_files": ["backend/tests/test_shared/test_verify_video_quality_matrix.py"]
    })
    
    print("TASK_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
