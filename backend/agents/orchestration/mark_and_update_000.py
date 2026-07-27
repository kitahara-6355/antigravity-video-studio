# -*- coding: utf-8 -*-
import os
import time
import json
import sqlite3
import asyncio
from pathlib import Path
from PIL import Image
from typing import Optional, Dict, Any

from backend.agents.stage_bound_agent import StageBoundAgent
from backend.agents.orchestration import OrchestrationHub

def emit_warning(message: str):
    import logging
    logger = logging.getLogger("thumbnail_processor")
    logger.warning(message)

class ThumbnailProcessor:
    def generate_thumbnail(self, out_path: Path, width: int = 1280, height: int = 720, text: str = ""):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (width, height), color=(50, 80, 120))
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
    text: str = "",
    timeout: float = 30.0
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
            if time.time() - start_time > timeout:
                try:
                    hub = OrchestrationHub()
                    hub.mark_task_done(task_id, "fail", {"error": "TimeoutError: Task execution timed out"})
                except Exception as he:
                    emit_warning(f"OrchestrationHub reporting error on timeout: {he}")
                raise TimeoutError("Task execution timed out")
                
            conn = None
            row = None
            try:
                conn = agent._get_conn()
                if conn:
                    cursor = conn.execute("SELECT status, result, error FROM tasks WHERE id = ?", (task_id,))
                    row = cursor.fetchone()
                else:
                    emit_warning("Database connection is None")
            except (sqlite3.Error, AttributeError, Exception) as e:
                emit_warning(f"Database access error: {e}")
            finally:
                if conn:
                    try:
                        agent._close_conn(conn)
                    except Exception as ce:
                        emit_warning(f"Database connection close error: {ce}")
            
            if row:
                status, result_str, error = row
                if status == "COMPLETED":
                    report = json.loads(result_str)
                    hub = OrchestrationHub()
                    hub.mark_task_done(task_id, "pass", report)
                    break
                elif status == "FAILED":
                    try:
                        hub = OrchestrationHub()
                        hub.mark_task_done(task_id, "fail", {"error": error})
                    except Exception as he:
                        emit_warning(f"OrchestrationHub reporting error on task failure: {he}")
                    raise RuntimeError(f"Task failed: {error}")
            await asyncio.sleep(0.1)
    finally:
        await agent.stop()
