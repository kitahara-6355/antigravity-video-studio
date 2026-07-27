# -*- coding: utf-8 -*-
"""
Stage Bound Agent — 分散型ステージ内部エージェント (IMP-009)
中央オーケストレーターを介さず、SQLiteのタスクステータスを監視して自律的に起動・制御する。
"""
import sqlite3
import time
import asyncio
import logging
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)

class StageBoundAgent:
    def __init__(
        self,
        stage_name: str,
        db_path: str = ":memory:",
        poll_interval: float = 0.1,
        gateway: Optional[Any] = None,
    ):
        self.stage_name = stage_name
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.running = False
        self._cached_conn = None
        self._init_db()
        self.gateway = gateway
        self._own_gateway = False

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._cached_conn is None:
                self._cached_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            return self._cached_conn
        return sqlite3.connect(self.db_path)

    def _close_conn(self, conn: sqlite3.Connection):
        if self.db_path != ":memory:":
            conn.close()

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    stage TEXT,
                    status TEXT, -- PENDING, READY, RUNNING, COMPLETED, FAILED
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.commit()

            cursor = conn.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]

            if "result" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN result TEXT")
            if "retry_count" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0")
            if "max_retries" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN max_retries INTEGER DEFAULT 0")
            conn.commit()
        finally:
            self._close_conn(conn)

    async def register_task(self, task_id: str, initial_status: str = "PENDING", max_retries: int = 0):
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO tasks (id, stage, status, created_at, updated_at, max_retries) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, self.stage_name, initial_status, now, now, max_retries)
            )
            conn.commit()
        finally:
            self._close_conn(conn)

    async def start(self, process_func: Callable[[str], Any]):
        if hasattr(self, "_poll_task") and self._poll_task and not self._poll_task.done():
            logger.warning(f"[{self.stage_name.upper()} AGENT] Agent already started. Ignoring start request.")
            return
        self.running = True
        self._poll_task = asyncio.create_task(self._poll_loop(process_func))

    async def stop(self):
        self.running = False
        if hasattr(self, "_poll_task") and self._poll_task:
            self._poll_task.cancel()
            await asyncio.gather(self._poll_task, return_exceptions=True)
            self._poll_task = None
        if self._own_gateway and self.gateway:
            await self.gateway.stop()
            self.gateway = None
            self._own_gateway = False
        if self._cached_conn:
            try:
                self._cached_conn.close()
            except sqlite3.Error:
                pass
            self._cached_conn = None

    async def call_llm(self, prompt: str, model: str, config: Optional[Dict] = None, timeout: float = 60.0) -> str:
        """LocalAsyncGateway を用いて非同期で LLM 呼び出しを処理するインターフェース"""
        if self.gateway is None:
            from model_governance_local import LocalAsyncGateway
            self.gateway = LocalAsyncGateway(db_path=self.db_path)
            self._own_gateway = True

            async def _default_client_call(model_name: str, prompt_text: str, cfg: Optional[Dict]) -> str:
                try:
                    from google import genai
                    from google.genai import types
                    from google.genai.errors import APIError
                except ImportError as e:
                    logger.error(f"Default client call failed to import google.genai: {e}")
                    raise RuntimeError(f"Default client call failed to import: {e}") from e

                try:
                    client = genai.Client()
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda: client.models.generate_content(
                            model=model_name,
                            contents=prompt_text,
                            config=types.GenerateContentConfig(**(cfg or {}))
                        )
                    )
                    return response.text
                except (APIError, TypeError, ValueError, RuntimeError) as e:
                    logger.error(f"Default client call failed: {e}")
                    raise RuntimeError(f"Default client call failed: {e}") from e

            await self.gateway.start(_default_client_call)

        job_id = await self.gateway.enqueue_job(
            task=self.stage_name, prompt=prompt, model=model, config=config
        )

        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise RuntimeError(f"LLM Job {job_id} timed out after {timeout} seconds")

            job = await self.gateway.get_job(job_id)
            if not job:
                raise RuntimeError(f"LLM Job {job_id} not found in gateway")

            status = job.get("status")
            if status == "COMPLETED":
                return job.get("result", "")
            elif status == "FAILED":
                raise RuntimeError(f"LLM Job {job_id} failed: {job.get('error')}")

            await asyncio.sleep(0.05)

    async def _poll_loop(self, process_func: Callable[[str], Any]):
        while self.running:
            try:
                task = self._fetch_ready_task()
                if task:
                    task_id = task["id"]
                    current_retry = task.get("retry_count", 0) or 0
                    max_retries = task.get("max_retries", 0) or 0
                    
                    logger.info(f"[{self.stage_name.upper()} AGENT] Found READY task: {task_id} (Attempt {current_retry + 1}/{max_retries + 1}). Starting execution...")
                    
                    self._update_task_status(task_id, "RUNNING")
                    
                    try:
                        if asyncio.iscoroutinefunction(process_func):
                            res = await process_func(task_id)
                        else:
                            res = await asyncio.to_thread(process_func, task_id)
                        
                        res_str = str(res) if res is not None else None
                        self._update_task_status(task_id, "COMPLETED", result=res_str)
                        logger.info(f"[{self.stage_name.upper()} AGENT] Task {task_id} completed successfully.")
                    except Exception as e:
                        err_str = str(e)
                        if current_retry < max_retries:
                            next_retry = current_retry + 1
                            self._update_task_status(
                                task_id,
                                "READY",
                                error=err_str,
                                retry_count=next_retry
                            )
                            logger.warning(
                                f"[{self.stage_name.upper()} AGENT] Task {task_id} failed. "
                                f"Retrying ({next_retry}/{max_retries}). Error: {err_str}"
                            )
                        else:
                            self._update_task_status(task_id, "FAILED", error=err_str)
                            logger.error(f"[{self.stage_name.upper()} AGENT] Task {task_id} failed: {err_str}")
            except Exception as e:
                logger.error(f"[{self.stage_name.upper()} AGENT] Error in poll loop: {e}")
                
            await asyncio.sleep(self.poll_interval)

    def _fetch_ready_task(self) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE stage = ? AND status = 'READY' LIMIT 1",
                (self.stage_name,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        finally:
            self._close_conn(conn)
        return None

    def _update_task_status(
        self,
        task_id: str,
        status: str,
        error: Optional[str] = None,
        result: Optional[str] = None,
        retry_count: Optional[int] = None,
    ):
        now = time.time()
        conn = self._get_conn()
        try:
            updates = ["status = ?", "updated_at = ?"]
            params = [status, now]

            if error is not None:
                updates.append("error = ?")
                params.append(error)
            if result is not None:
                updates.append("result = ?")
                params.append(result)
            if retry_count is not None:
                updates.append("retry_count = ?")
                params.append(retry_count)

            params.append(task_id)
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, tuple(params))
            conn.commit()
        finally:
            self._close_conn(conn)

    async def get_task_status(self, task_id: str) -> Optional[str]:
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
        finally:
            self._close_conn(conn)
        return None


# ============================================================
# サムネイル生成・品質検証ロジック（backend/services/thumbnail_analyzer.py に統合）
# ============================================================

def generate_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail"
):
    """backend.services.thumbnail_analyzer の高品質生成器に委譲する"""
    try:
        from backend.services.thumbnail_analyzer import thumbnail_analyzer
    except ImportError:
        from services.thumbnail_analyzer import thumbnail_analyzer
    return thumbnail_analyzer.generate_thumbnail(
        output_path, width=width, height=height, text=text
    )

def validate_thumbnail(file_path) -> dict:
    """backend.services.thumbnail_analyzer の検証器に委譲する"""
    try:
        from backend.services.thumbnail_analyzer import thumbnail_analyzer
    except ImportError:
        from services.thumbnail_analyzer import thumbnail_analyzer
    return thumbnail_analyzer.validate_thumbnail(file_path)

async def resolve_thumbnail_task(self, task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する non-member 非同期タスク処理
    """
    import json
    from pathlib import Path
    output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    width = getattr(self, "width", 1280)
    height = getattr(self, "height", 720)
    text = getattr(self, "text", "Thumbnail")
    
    generate_thumbnail(output_path, width=width, height=height, text=text)
    result_info = validate_thumbnail(output_path)
    return json.dumps(result_info)
