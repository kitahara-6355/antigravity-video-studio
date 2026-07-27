import sys
sys.path.insert(0, '.')
import json
import os
import uuid
import time
import asyncio
from pathlib import Path
from PIL import Image, ImageDraw
from backend.agents.orchestration import OrchestrationHub
from backend.agents.stage_bound_agent import StageBoundAgent

DEFAULT_CONVERSATION_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"

def initialize_hub(conversation_id: str = DEFAULT_CONVERSATION_ID) -> OrchestrationHub:
    """OrchestrationHubを初期化し、心拍を更新します。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub

def mark_completed_tasks(hub: OrchestrationHub) -> None:
    """指定されたタスクの完了マークを記録します。"""
    # test_weaver-001 完了マーク
    hub.mark_task_done("T-batch_a97ee3-test_weaver-001", "pass", {
        "message": "decision_logger.py のテスト拡充。分岐カバレッジ 99% -> 100% へ向上。",
        "changed_files": ["backend/tests/test_decision_logger_branches.py"]
    })

    # bug_hunter-000 完了マーク
    hub.mark_task_done("T-batch_a97ee3-bug_hunter-000", "pass", {
        "message": "metadata_generator.py のエラーハンドリング強化とTDR登録（TD-834）。",
        "changed_files": [
            "backend/metadata_generator.py",
            "backend/tests/test_metadata_generator.py",
            "backend/agents/memory/technical_debt_index.json"
        ]
    })
    print("TASKS_MARKED_DONE")

def print_status(hub: OrchestrationHub) -> None:
    """最新ステータスを取得して出力します。"""
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

# ============================================================
# サムネイル生成・品質検証・StageBoundAgent連携ロジック (Phase 27 改善版)
# ============================================================

def generate_thumbnail_p27(
    output_path: str,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail"
) -> Path:
    """
    Pillowを使用して、原子的に指定された解像度とテキストでサムネイル画像を生成する。
    """
    from PIL import Image, ImageDraw
    import uuid
    import os
    from pathlib import Path
    
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    if text is None:
        text = ""
    else:
        text = str(text)
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # アスペクト比チェック (16:9)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    # 原子的な書き込み (Atomic Write)
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path, "PNG")
        
        # os.replace によりアトミックに上書き置換 (Windows対応)
        os.replace(temp_path, output_path)
    except Exception as e:
        raise RuntimeError(f"Failed to generate thumbnail atomically: {e}")
    finally:
        # 一時ファイルの確実なクリーンアップ
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        
    return output_path

def validate_thumbnail_p27(file_path: str) -> dict:
    """
    サムネイル画像の品質要件を検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    from PIL import Image
    from pathlib import Path
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Thumbnail path is not a file: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 破損検証 (verify)
    try:
        with Image.open(file_path) as img:
            img.verify()
            img.close()
    except Exception as e:
        raise ValueError(f"Image verification failed (corrupted): {e}")
        
    # 破損検証 (load) - ピクセルロードまで行い完全性を検証
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
            img.close()
    except Exception as e:
        raise ValueError(f"Image load failed (corrupted): {e}")
        
    # 解像度検証
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    # アスペクト比検証
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

async def run_thumbnail_task_p27(
    task_id: str,
    db_path: str,
    output_path: str,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail",
    max_retries: int = 2,
    process_func_override=None
) -> str:
    """
    StageBoundAgent と連携してサムネイル生成タスクを実行し、
    自動リトライや結果保存、DBマイグレーションの動作を確認する。
    """
    agent = StageBoundAgent(
        stage_name="thumbnail_p27",
        db_path=db_path,
        poll_interval=0.01
    )
    
    if process_func_override is None:
        async def default_process_func(tid: str) -> str:
            generate_thumbnail_p27(output_path, width=width, height=height, text=text)
            res_info = validate_thumbnail_p27(output_path)
            return json.dumps(res_info)
        func = default_process_func
    else:
        func = process_func_override
        
    await agent.register_task(task_id, initial_status="READY", max_retries=max_retries)
    await agent.start(func)
    
    # タスクが完了または失敗するまで待機
    start_time = time.time()
    result_status = None
    while time.time() - start_time < 5.0:  # 最大5秒待機
        result_status = await agent.get_task_status(task_id)
        if result_status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    # タイムアウト時のハンドリング (DBステータスをFAILEDに更新)
    if result_status not in ("COMPLETED", "FAILED"):
        agent._update_task_status(
            task_id,
            "FAILED",
            error="Task execution timed out after 5.0 seconds"
        )
        result_status = "FAILED"
        
    await agent.stop()
    return result_status

def main() -> None:
    hub = initialize_hub()
    mark_completed_tasks(hub)
    print_status(hub)

if __name__ == "__main__":  # pragma: no cover
    main()
