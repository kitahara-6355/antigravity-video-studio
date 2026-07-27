# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock
import pytest
from backend.model_governance_local import LocalAsyncGateway

@pytest.mark.asyncio
async def test_local_gateway_lifecycle():
    gateway = LocalAsyncGateway(db_path=":memory:", rpm_limit=5, tpm_limit=100)
    
    job_id = await gateway.enqueue_job(
        task="test_task",
        prompt="Hello Test",
        model="gemini-1.5-flash",
        config={"temp": 0.5}
    )
    assert job_id is not None

    job = await gateway.get_job(job_id)
    assert job["status"] == "PENDING"
    assert job["task"] == "test_task"

    async def mock_client(model, prompt, config):
        return f"Response to {prompt}"

    await gateway.start(mock_client)
    await asyncio.sleep(0.3)
    
    job_done = await gateway.get_job(job_id)
    assert job_done["status"] == "COMPLETED"
    assert job_done["result"] == "Response to Hello Test"

    metrics = gateway._get_active_metrics()
    assert metrics["rpm"] == 1
    assert metrics["tpm"] == 20  # prompt length 10 * 2

    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_rate_limit_cooldown():
    gateway = LocalAsyncGateway(db_path=":memory:", rpm_limit=1, tpm_limit=10)
    
    gateway._log_request("gemini-1.5-flash", 10)
    
    metrics = gateway._get_active_metrics()
    assert metrics["rpm"] >= 1
    
    job_id = await gateway.enqueue_job(task="t", prompt="p", model="m")
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    # クールダウンが走り、待機状態になるのを少し待つ
    await asyncio.sleep(0.1)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "PENDING"
    
    # request_logs テーブルのレコードを過去（61秒前）に更新してクールダウンから復帰させる
    conn = gateway._get_conn()
    conn.execute("UPDATE request_logs SET timestamp = timestamp - 61.0")
    conn.commit()
    gateway._close_conn(conn)
    
    # ループが再開してジョブが処理されるのを待つ
    await asyncio.sleep(0.6)
    
    job_done = await gateway.get_job(job_id)
    assert job_done["status"] == "COMPLETED"
    assert job_done["result"] == "OK"
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_errors():
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    job_id_fail = await gateway.enqueue_job(task="fail", prompt="p", model="m")
    
    async def failing_client(model, prompt, config):
        raise ValueError("Fatal API Error")
        
    await gateway.start(failing_client)
    await asyncio.sleep(0.2)
    
    job = await gateway.get_job(job_id_fail)
    assert job["status"] == "FAILED"
    assert "Fatal API Error" in job["error"]
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_429_retry():
    # テストを高速化するため initial_backoff を小さく設定
    gateway = LocalAsyncGateway(db_path=":memory:", initial_backoff=0.01)
    
    job_id_429 = await gateway.enqueue_job(task="retry", prompt="p", model="m")
    
    call_count = 0
    async def retry_client(model, prompt, config):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("RESOURCE_EXHAUSTED 429 error")
        return "Success After 429"
        
    await gateway.start(retry_client)
    await asyncio.sleep(0.3)
    
    job = await gateway.get_job(job_id_429)
    assert job["status"] == "COMPLETED"
    assert job["result"] == "Success After 429"
    
    await gateway.stop()


@pytest.mark.asyncio
async def test_local_gateway_file_db():
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        gateway = LocalAsyncGateway(db_path=temp_path, rpm_limit=5, tpm_limit=100)
        
        job_id = await gateway.enqueue_job(
            task="test_file_db",
            prompt="Hello File DB",
            model="gemini-1.5-flash"
        )
        assert job_id is not None
        
        job = await gateway.get_job(job_id)
        assert job["task"] == "test_file_db"
        
        async def mock_client(model, prompt, config):
            return "File DB OK"
            
        await gateway.start(mock_client)
        await asyncio.sleep(0.3)
        
        job_done = await gateway.get_job(job_id)
        assert job_done["status"] == "COMPLETED"
        
        await gateway.stop()
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

@pytest.mark.asyncio
async def test_local_gateway_non_existent_job():
    gateway = LocalAsyncGateway(db_path=":memory:")
    job = await gateway.get_job("non-existent-uuid-12345")
    assert job is None
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_close_error_handling():
    gateway = LocalAsyncGateway(db_path=":memory:")
    # 元の接続を明示的にクローズして ResourceWarning を防ぐ
    if gateway._cached_conn:
        gateway._cached_conn.close()
        
    mock_conn = MagicMock()
    mock_conn.close.side_effect = sqlite3.Error("Mock Close Error")
    gateway._cached_conn = mock_conn
    
    await gateway.stop()
    assert gateway._cached_conn is None

@pytest.mark.asyncio
async def test_local_gateway_rate_limit_cooldown_and_resume():
    gateway = LocalAsyncGateway(db_path=":memory:", rpm_limit=1, tpm_limit=10)
    gateway._log_request("gemini-1.5-flash", 10)
    
    job_id = await gateway.enqueue_job(task="cooldown_test", prompt="p", model="m")
    
    async def mock_client(model, prompt, config):
        return "Resumed OK"
        
    await gateway.start(mock_client)
    
    await asyncio.sleep(0.2)
    job = await gateway.get_job(job_id)
    assert job["status"] == "PENDING"
    
    conn = gateway._get_conn()
    conn.execute("DELETE FROM request_logs")
    conn.commit()
    
    await asyncio.sleep(0.7)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "COMPLETED"
    assert job["result"] == "Resumed OK"
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_wal_and_timeout(tmp_path):
    db_file = tmp_path / "test_gov.db"
    gateway = LocalAsyncGateway(db_path=str(db_file), initial_backoff=0.01)
    
    # Verify WAL mode is active
    conn = gateway._get_conn()
    cursor = conn.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    gateway._close_conn(conn)
    
    assert mode.lower() == "wal"
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_max_retries_reached():
    gateway = LocalAsyncGateway(db_path=":memory:", max_retries=2, initial_backoff=0.01)
    
    job_id = await gateway.enqueue_job(task="fail_limit", prompt="p", model="m")
    
    async def retry_client(model, prompt, config):
        raise RuntimeError("RESOURCE_EXHAUSTED 429 error")
        
    await gateway.start(retry_client)
    await asyncio.sleep(0.3)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "FAILED"
    assert "Max retries reached" in job["error"]
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_backoff_concurrency():
    # Longer backoff to check non-blocking behavior
    gateway = LocalAsyncGateway(db_path=":memory:", initial_backoff=0.5)
    
    job_id_a = await gateway.enqueue_job(task="task_a", prompt="p_a", model="m")
    
    call_count = {}
    async def mock_client(model, prompt, config):
        call_count[prompt] = call_count.get(prompt, 0) + 1
        if prompt == "p_a" and call_count[prompt] == 1:
            raise RuntimeError("RESOURCE_EXHAUSTED 429 error")
        return f"Done {prompt}"
        
    await gateway.start(mock_client)
    
    # Wait until job A fails with 429 and enters backoff
    await asyncio.sleep(0.1)
    
    job_a = await gateway.get_job(job_id_a)
    assert job_a["status"] == "PENDING"
    assert job_a["backoff_until"] > time.time()
    
    # Enqueue job B which should run and finish immediately
    job_id_b = await gateway.enqueue_job(task="task_b", prompt="p_b", model="m")
    
    await asyncio.sleep(0.2)
    job_b = await gateway.get_job(job_id_b)
    job_a_delayed = await gateway.get_job(job_id_a)
    
    assert job_b["status"] == "COMPLETED"
    assert job_b["result"] == "Done p_b"
    assert job_a_delayed["status"] == "PENDING"
    
    # Wait until job A's backoff finishes
    await asyncio.sleep(0.5)
    job_a_final = await gateway.get_job(job_id_a)
    assert job_a_final["status"] == "COMPLETED"
    assert job_a_final["result"] == "Done p_a"
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_get_nonexistent_job():
    gateway = LocalAsyncGateway(db_path=":memory:")
    job = await gateway.get_job("non-existent-id")
    assert job is None
    await gateway.stop()

class MockWALErrorConnection(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        if "PRAGMA journal_mode=WAL" in sql:
            raise sqlite3.Error("Mock WAL Error")
        return super().execute(sql, *args, **kwargs)

@pytest.mark.asyncio
async def test_local_gateway_wal_pragma_error_memory(monkeypatch):
    original_connect = sqlite3.connect
    def mock_connect(*args, **kwargs):
        kwargs['factory'] = MockWALErrorConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    
    gateway = LocalAsyncGateway(db_path=":memory:")
    if gateway._cached_conn:
        gateway._cached_conn.close()
    gateway._cached_conn = None
    conn = gateway._get_conn()
    assert conn is not None
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_wal_pragma_error_file(monkeypatch, tmp_path):
    db_file = tmp_path / "test_error.db"
    original_connect = sqlite3.connect
    def mock_connect(*args, **kwargs):
        kwargs['factory'] = MockWALErrorConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", mock_connect)
    
    gateway = LocalAsyncGateway(db_path=str(db_file))
    conn = gateway._get_conn()
    assert conn is not None
    gateway._close_conn(conn)
    await gateway.stop()


@pytest.mark.asyncio
async def test_local_gateway_special_config():
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    special_config = {
        "nested": {"key": "value", "list": [1, 2, 3]},
        "special_chars": "!@#$%^&*()_+",
        "japanese": "日本語テスト"
    }
    
    job_id = await gateway.enqueue_job(
        task="special_config_task",
        prompt="Test Prompt",
        model="gemini-1.5-flash",
        config=special_config
    )
    
    job = await gateway.get_job(job_id)
    assert job is not None
    loaded_config = json.loads(job["config"])
    assert loaded_config == special_config
    
    await gateway.stop()


@pytest.mark.asyncio
async def test_local_gateway_zero_rate_limit():
    gateway = LocalAsyncGateway(db_path=":memory:", rpm_limit=0, tpm_limit=0)
    
    gateway._log_request("gemini-1.5-flash", 1)
    
    job_id = await gateway.enqueue_job(task="blocked_task", prompt="p", model="m")
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    await asyncio.sleep(0.1)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "PENDING"
    
    await gateway.stop()


@pytest.mark.asyncio
async def test_local_gateway_retry_jitter_bounds():
    gateway = LocalAsyncGateway(db_path=":memory:", initial_backoff=1.0, max_retries=1)
    
    job_id = await gateway.enqueue_job(task="jitter_task", prompt="p", model="m")
    
    original_retry = gateway._retry_job
    captured_delay = None
    
    def mock_retry(job_id, error, next_retry_count, delay):
        nonlocal captured_delay
        captured_delay = delay
        original_retry(job_id, error, next_retry_count, delay)
        
    gateway._retry_job = mock_retry
    
    async def failing_client(model, prompt, config):
        raise RuntimeError("RESOURCE_EXHAUSTED 429 error")
        
    await gateway.start(failing_client)
    await asyncio.sleep(0.2)
    
    assert captured_delay is not None
    assert 0.8 <= captured_delay <= 1.2
    
    await gateway.stop()



@pytest.mark.asyncio
async def test_local_gateway_cached_connection_cleanup():
    gateway = LocalAsyncGateway(db_path=":memory:")
    conn = gateway._get_conn()
    assert gateway._cached_conn is conn
    
    # Verify the connection is active
    conn.execute("SELECT 1")
    
    await gateway.stop()
    assert gateway._cached_conn is None
    
    # Verify the connection is closed
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn.execute("SELECT 1")

@pytest.mark.asyncio
async def test_local_gateway_stop_gather_exception(monkeypatch):
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    
    # Mock asyncio.gather to raise an exception when awaited
    async def mock_gather_raise(*args, **kwargs):
        raise ValueError("Mocked gather error")
        
    monkeypatch.setattr("backend.model_governance_local.asyncio.gather", mock_gather_raise)
    
    # The exception should be caught internally and stop() should complete successfully
    await gateway.stop()
    assert gateway._process_task is None

@pytest.mark.asyncio
async def test_local_gateway_db_error_on_complete(monkeypatch):
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    job_id = await gateway.enqueue_job(task="db_err_task", prompt="p", model="m")
    
    def mock_complete_job(job_id, result):
        raise sqlite3.Error("Mock complete error")
        
    captured_fail_args = []
    def mock_fail_job(job_id, error):
        captured_fail_args.append((job_id, error))
        raise sqlite3.Error("Mock fail error")
        
    monkeypatch.setattr(gateway, "_complete_job", mock_complete_job)
    monkeypatch.setattr(gateway, "_fail_job", mock_fail_job)
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    await asyncio.sleep(0.2)
    
    assert len(captured_fail_args) == 1
    assert captured_fail_args[0][0] == job_id
    assert "Database Error during completion" in captured_fail_args[0][1]
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_invalid_json_config():
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    # Directly insert corrupted JSON config
    conn = gateway._get_conn()
    job_id = "invalid-json-job"
    conn.execute(
        "INSERT INTO api_jobs (id, task, prompt, model, config, status, created_at, retry_count, backoff_until) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0.0)",
        (job_id, "test_task", "prompt", "model", "{invalid_json: true", "PENDING", time.time())
    )
    conn.commit()
    gateway._close_conn(conn)
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    await asyncio.sleep(0.3)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "FAILED"
    assert "Invalid JSON config" in job["error"]
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_process_loop_resilience(monkeypatch):
    gateway = LocalAsyncGateway(db_path=":memory:")
    
    original_fetch = gateway._fetch_next_job
    call_count = 0
    
    def mock_fetch():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise sqlite3.OperationalError("database is locked (mocked)")
        return original_fetch()
        
    monkeypatch.setattr(gateway, "_fetch_next_job", mock_fetch)
    
    job_id = await gateway.enqueue_job(task="resilient_task", prompt="p", model="m")
    
    async def mock_client(model, prompt, config):
        return "Resilient OK"
        
    await gateway.start(mock_client)
    
    # Wait at least 1.3 seconds as the loop sleeps for 1.0 second upon error
    await asyncio.sleep(1.3)
    
    job = await gateway.get_job(job_id)
    assert job["status"] == "COMPLETED"
    assert job["result"] == "Resilient OK"
    
    await gateway.stop()

@pytest.mark.asyncio
async def test_local_gateway_migration_error_handling(monkeypatch):
    db_err = sqlite3.OperationalError("Some weird database error")
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    
    # We monkeypatch sqlite3.connect to return mock_conn
    monkeypatch.setattr("backend.model_governance_local.sqlite3.connect", lambda *a, **k: mock_conn)
    
    # Test case 1: error on retry_count migration
    def execute_side_effect_retry_count(sql, *args):
        if "ALTER TABLE" in sql and "retry_count" in sql:
            raise db_err
        return mock_cursor
        
    mock_conn.execute.side_effect = execute_side_effect_retry_count
    with pytest.raises(sqlite3.OperationalError, match="Some weird database error"):
        LocalAsyncGateway(db_path="dummy_path")

    # Test case 2: error on backoff_until migration
    def execute_side_effect_backoff(sql, *args):
        if "ALTER TABLE" in sql and "backoff_until" in sql:
            raise db_err
        return mock_cursor
        
    mock_conn.execute.side_effect = execute_side_effect_backoff
    with pytest.raises(sqlite3.OperationalError, match="Some weird database error"):
        LocalAsyncGateway(db_path="dummy_path")

@pytest.mark.asyncio
async def test_local_gateway_update_status_running_db_error(monkeypatch):
    gateway = LocalAsyncGateway(db_path=":memory:")
    job_id = await gateway.enqueue_job(task="run_err_task", prompt="p", model="m")
    
    # Mock _update_job_status to raise sqlite3.Error when status is RUNNING
    def mock_update_status(jid, status):
        if status == "RUNNING":
            raise sqlite3.Error("Mock db update error")
        # Let default work if called with other states
        conn = gateway._get_conn()
        try:
            conn.execute("UPDATE api_jobs SET status = ? WHERE id = ?", (status, jid))
            conn.commit()
        finally:
            gateway._close_conn(conn)
            
    monkeypatch.setattr(gateway, "_update_job_status", mock_update_status)
    
    async def mock_client(model, prompt, config):
        return "OK"
        
    await gateway.start(mock_client)
    await asyncio.sleep(0.2)
    
    # Since exception is raised inside _process_single_job and not caught there (it raises),
    # it is caught by the outer loop in _process_loop and logged, and the job status remains PENDING
    # The process loop should survive this error
    job = await gateway.get_job(job_id)
    assert job["status"] == "PENDING"
    
    await gateway.stop()

