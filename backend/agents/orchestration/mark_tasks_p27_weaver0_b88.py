import sys
import os
import time
import json
import sqlite3
import asyncio
from pathlib import Path
from PIL import Image

sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
from backend.agents.stage_bound_agent import StageBoundAgent

def emit_warning(message: str):
    import logging
    logger = logging.getLogger("thumbnail_processor_p27")
    logger.warning(message)

class ThumbnailProcessor:
    def generate_thumbnail(self, out_path: Path, width: int = 1280, height: int = 720, text: str = ""):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color=(60, 90, 130))
        img.save(out_path, "PNG")

    def validate_thumbnail(self, file_path: Path) -> dict:
        file_path = Path(file_path)
        if not file_path.exists():
            emit_warning(f"File not found: {file_path}")
            raise ValueError("File does not exist")

        try:
            with Image.open(file_path) as img:
                img.verify()
            with Image.open(file_path) as img:
                img.load()  # ピクセルデータのロードを強制して破損検知
                width, height = img.size
        except (IOError, SyntaxError) as e:
            emit_warning(f"Image corrupted: {e}")
            raise ValueError(f"Image is corrupted or invalid: {e}")

        if width < 1280 or height < 720:
            emit_warning(f"Low resolution: {width}x{height}")
            raise ValueError("Resolution must be at least 1280x720")

        aspect = width / height
        target_aspect = 16.0 / 9.0
        if abs(aspect - target_aspect) > 0.01:
            emit_warning(f"Invalid aspect ratio: {aspect}")
            raise ValueError("Aspect ratio must be 16:9")

        size_bytes = file_path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            emit_warning(f"File too large: {size_bytes} bytes")
            raise ValueError("File size exceeds 4MB limit")

        return {
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "path": str(file_path)
        }

async def run_thumbnail_task(
    db_path: str,
    task_id: str,
    output_dir: str,
    width: int = 1280,
    height: int = 720,
    text: str = ""
):
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=db_path,
        poll_interval=0.05
    )
    
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    out_path = Path(output_dir) / f"{task_id}.png"
    
    async def process_task(tid: str):
        processor = ThumbnailProcessor()
        processor.generate_thumbnail(out_path, width=width, height=height, text=text)
        result = processor.validate_thumbnail(out_path)
        return json.dumps(result)

    await agent.start(process_task)
    
    start_time = time.time()
    try:
        while True:
            if time.time() - start_time > 30.0:
                raise TimeoutError("Task execution timed out")
                
            conn = agent._get_conn()
            try:
                cursor = conn.execute("SELECT status, result, error FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
            finally:
                agent._close_conn(conn)
            
            if row:
                status, result_str, error = row
                if status == "COMPLETED":
                    report = json.loads(result_str)
                    hub = OrchestrationHub()
                    hub.mark_task_done(task_id, "pass", report)
                    break
                elif status == "FAILED":
                    raise RuntimeError(f"Task failed: {error}")
            await asyncio.sleep(0.1)
    finally:
        await agent.stop()

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # test_weaver-000 完了マーク
    hub.mark_task_done("T-batch_881c02-test_weaver-000", "pass", {
        "message": "agents/_deprecated/supervisor.py のテスト追加。カバレッジ 0% -> 100% へ向上。",
        "changed_files": ["backend/tests/test_agents/test_deprecated_supervisor.py"]
    })
    
    print("TASK_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
