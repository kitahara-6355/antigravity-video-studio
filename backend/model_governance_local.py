# -*- coding: utf-8 -*-
"""
Local Async Gateway — ローカル完結型非同期 API ゲートウェイ (IMP-014)
SQLite ジョブキュー、レート制限監視、動的クールダウンを実装。
"""
import asyncio
import json
import logging
import random
import sqlite3
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class LocalAsyncGateway:
    def __init__(self, db_path: str = ":memory:", rpm_limit: int = 15, tpm_limit: int = 1000000,
                 initial_backoff: float = 0.5, max_backoff: float = 60.0,
                 backoff_factor: float = 2.0, max_retries: int = 5):
        self.db_path = db_path
        self.rpm_limit = rpm_limit
        self.tpm_limit = tpm_limit
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_factor = backoff_factor
        self.max_retries = max_retries
        self.running = False
        self._cached_conn = None
        self._process_task = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._cached_conn is None:
                self._cached_conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
                try:
                    self._cached_conn.execute("PRAGMA journal_mode=WAL")
                except sqlite3.Error as e:
                    logger.warning(f"Failed to set WAL journal mode for in-memory cache: {e}")
            return self._cached_conn
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error as e:
            logger.warning(f"Failed to set WAL journal mode for DB file: {e}")
        return conn

    def _close_conn(self, conn: sqlite3.Connection):
        if self.db_path != ":memory:":
            conn.close()

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_jobs (
                    id TEXT PRIMARY KEY,
                    task TEXT,
                    prompt TEXT,
                    model TEXT,
                    config TEXT,
                    status TEXT,
                    result TEXT,
                    error TEXT,
                    created_at REAL,
                    completed_at REAL,
                    retry_count INTEGER DEFAULT 0,
                    backoff_until REAL DEFAULT 0.0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    timestamp REAL,
                    model TEXT,
                    tokens_used INTEGER
                )
            """)
            # Schema migration for existing DB
            try:
                conn.execute("ALTER TABLE api_jobs ADD COLUMN retry_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower() and "already exists" not in str(e).lower():
                    logger.error(f"Migration error (retry_count): {e}")
                    raise
            try:
                conn.execute("ALTER TABLE api_jobs ADD COLUMN backoff_until REAL DEFAULT 0.0")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower() and "already exists" not in str(e).lower():
                    logger.error(f"Migration error (backoff_until): {e}")
                    raise
            conn.commit()
        finally:
            self._close_conn(conn)

    async def enqueue_job(self, task: str, prompt: str, model: str, config: Optional[Dict] = None) -> str:
        job_id = str(uuid.uuid4())
        config_json = json.dumps(config or {})
        created_at = time.time()
        
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO api_jobs (id, task, prompt, model, config, status, created_at, retry_count, backoff_until) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.0)",
                (job_id, task, prompt, model, config_json, "PENDING", created_at)
            )
            conn.commit()
        finally:
            self._close_conn(conn)
        return job_id

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM api_jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        finally:
            self._close_conn(conn)
        return None

    def _get_active_metrics(self) -> Dict[str, Any]:
        now = time.time()
        one_minute_ago = now - 60.0
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) as count, SUM(tokens_used) as tokens FROM request_logs WHERE timestamp >= ?",
                (one_minute_ago,)
            )
            row = cursor.fetchone()
            count = row[0] or 0
            tokens = row[1] or 0
            return {"rpm": count, "tpm": tokens}
        finally:
            self._close_conn(conn)

    def _log_request(self, model: str, tokens: int):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO request_logs (timestamp, model, tokens_used) VALUES (?, ?, ?)",
                (time.time(), model, tokens)
            )
            conn.commit()
        finally:
            self._close_conn(conn)

    async def start(self, client_call_func):
        """
        キューの非同期処理ループを開始。
        client_call_func: model, prompt, config を受け取り API の応答テキストを返す非同期関数。
        """
        self.running = True
        self._process_task = asyncio.create_task(self._process_loop(client_call_func))

    async def stop(self):
        self.running = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await asyncio.gather(self._process_task, return_exceptions=True)
            except (ValueError, TypeError, RuntimeError) as e:
                logger.warning(f"Exception during stop gather: {e}")
            self._process_task = None
        if self._cached_conn:
            try:
                self._cached_conn.close()
            except sqlite3.Error as e:
                logger.warning(f"Failed to close cached connection: {e}")
            self._cached_conn = None

    def _is_rate_limited(self, metrics: Dict[str, Any]) -> bool:
        """RPM または TPM が制限の 80% に達しているか判定する"""
        rpm = metrics["rpm"]
        tpm = metrics["tpm"]
        return rpm >= self.rpm_limit * 0.8 or tpm >= self.tpm_limit * 0.8

    async def _cooldown_if_rate_limited(self) -> bool:
        """RPM または TPM が制限の 80% に達している場合、クールダウンのために一時待機する"""
        metrics = self._get_active_metrics()
        if self._is_rate_limited(metrics):
            logger.warning(
                f"Local Rate Limit threshold reached (RPM: {metrics['rpm']}/{self.rpm_limit}, "
                f"TPM: {metrics['tpm']}/{self.tpm_limit}). Cooldown..."
            )
            await asyncio.sleep(0.5)
            return True
        return False

    def _estimate_tokens(self, prompt: str) -> int:
        """簡易トークン見積もり（1文字2トークン）"""
        return len(prompt) * 2

    async def _process_single_job(self, job: Dict[str, Any], client_call_func) -> None:
        """単一のジョブを実行して結果を保存する"""
        job_id = job["id"]
        model = job["model"]
        prompt = job["prompt"]
        
        try:
            config = json.loads(job["config"])
        except (json.JSONDecodeError, TypeError) as parse_exc:
            logger.error(f"Failed to parse job config for job {job_id}: {parse_exc}")
            self._fail_job(job_id, f"Invalid JSON config: {str(parse_exc)}")
            return

        try:
            self._update_job_status(job_id, "RUNNING")
        except sqlite3.Error as db_exc:
            logger.error(f"Failed to update job status to RUNNING for job {job_id}: {db_exc}")
            raise

        try:
            result = await client_call_func(model, prompt, config)
        except (ValueError, TypeError, RuntimeError, OSError, sqlite3.Error) as api_exc:
            # クライアント関数呼び出しでのエラー（API制限など）はジョブ失敗ハンドラへ
            await self._handle_job_failure(job, api_exc)
            return

        try:
            estimated_tokens = self._estimate_tokens(prompt)
            self._complete_job(job_id, result)
            self._log_request(model, estimated_tokens)
        except sqlite3.Error as db_exc:
            logger.error(f"Failed to record completed job {job_id} in DB: {db_exc}")
            try:
                self._fail_job(job_id, f"Database Error during completion: {str(db_exc)}")
            except sqlite3.Error as inner_exc:
                logger.error(f"Failed to fail job {job_id} after DB error: {inner_exc}")

    def _is_temporary_error(self, error_msg: str) -> bool:
        """429 または RESOURCE_EXHAUSTED などの一時的なエラーか判定する"""
        return "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg

    def _calculate_backoff_delay(self, retry_count: int) -> float:
        """指数バックオフにジッターを乗せた待機時間を計算する"""
        delay = self.initial_backoff * (self.backoff_factor ** retry_count)
        delay = min(delay, self.max_backoff)
        jitter = random.uniform(0.8, 1.2)
        return delay * jitter

    async def _handle_temporary_failure(self, job: Dict[str, Any], error_msg: str) -> None:
        """一時的なエラー発生時に、リトライ上限を確認してリトライまたは失敗に移行する"""
        job_id = job["id"]
        current_retry = job.get("retry_count", 0) or 0
        if current_retry < self.max_retries:
            actual_delay = self._calculate_backoff_delay(current_retry)
            logger.warning(
                f"Local Async Gateway: API 429 detected for job {job_id} (retry {current_retry + 1}/{self.max_retries}). "
                f"Retrying in {actual_delay:.2f}s..."
            )
            self._retry_job(job_id, error_msg, current_retry + 1, actual_delay)
        else:
            logger.error(f"Local Async Gateway: Max retries ({self.max_retries}) reached for job {job_id}. Failing...")
            self._fail_job(job_id, f"Max retries reached. Last error: {error_msg}")

    async def _handle_job_failure(self, job: Dict[str, Any], error: Exception) -> None:
        """ジョブ実行中のエラー（特に429レート制限）をハンドリングする"""
        job_id = job["id"]
        error_msg = str(error)
        
        if self._is_temporary_error(error_msg):
            await self._handle_temporary_failure(job, error_msg)
        else:
            self._fail_job(job_id, error_msg)

    async def _process_loop(self, client_call_func):
        while self.running:
            try:
                if await self._cooldown_if_rate_limited():
                    continue

                job = self._fetch_next_job()
                if not job:
                    await asyncio.sleep(0.1)
                    continue

                await self._process_single_job(job, client_call_func)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                logger.info("Local Async Gateway: Process loop cancelled.")
                break
            except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as e:
                logger.error(f"Local Async Gateway: Unexpected error in process loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    def _fetch_next_job(self) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM api_jobs WHERE status = 'PENDING' AND backoff_until <= ? ORDER BY created_at ASC LIMIT 1",
                (time.time(),)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        finally:
            self._close_conn(conn)
        return None

    def _update_job_status(self, job_id: str, status: str):
        conn = self._get_conn()
        try:
            conn.execute("UPDATE api_jobs SET status = ? WHERE id = ?", (status, job_id))
            conn.commit()
        finally:
            self._close_conn(conn)

    def _retry_job(self, job_id: str, error: str, next_retry_count: int, delay: float):
        now = time.time()
        backoff_until = now + delay
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE api_jobs SET status = 'PENDING', error = ?, retry_count = ?, backoff_until = ? WHERE id = ?",
                (error, next_retry_count, backoff_until, job_id)
            )
            conn.commit()
        finally:
            self._close_conn(conn)

    def _complete_job(self, job_id: str, result: str):
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE api_jobs SET status = 'COMPLETED', result = ?, completed_at = ? WHERE id = ?",
                (result, now, job_id)
            )
            conn.commit()
        finally:
            self._close_conn(conn)

    def _fail_job(self, job_id: str, error: str):
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE api_jobs SET status = 'FAILED', error = ?, completed_at = ? WHERE id = ?",
                (error, now, job_id)
            )
            conn.commit()
        finally:
            self._close_conn(conn)
