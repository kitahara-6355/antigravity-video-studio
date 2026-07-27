# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import pytest
from backend.agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_stage_bound_agent_close_conn_non_memory_direct(tmp_path):
    db_file = tmp_path / "close_non_memory.db"
    agent = StageBoundAgent(stage_name="test", db_path=str(db_file))
    conn = sqlite3.connect(str(db_file))
    
    # db_path が ":memory:" でない場合の close 処理を検証 (39-40行目のカバー)
    agent._close_conn(conn)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_default_client_call_exception_direct(tmp_path):
    db_file = tmp_path / "default_client_direct.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    from unittest.mock import patch, MagicMock
    
    captured_client_call = None
    
    async def mock_start(self, client_call_func):
        nonlocal captured_client_call
        captured_client_call = client_call_func
        self.running = True
        
    with patch("model_governance_local.LocalAsyncGateway.start", mock_start):
        with patch("google.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.models.generate_content.side_effect = Exception("Direct client exception")
            mock_client_class.return_value = mock_client
            
            # call_llm を経由させて gateway と _default_client_call をセットアップ
            try:
                await agent.call_llm(prompt="Hello", model="gemini-2.5-flash", timeout=0.01)
            except Exception:
                pass
                
            assert captured_client_call is not None
            
            # 同一スレッド・コンテキストで直接 _default_client_call を実行して例外スローを確実にトレースする (119行目のカバー)
            with pytest.raises(Exception) as exc_info:
                await captured_client_call("gemini-2.5-flash", "Hello", None)
            assert "Direct client exception" in str(exc_info.value)
            
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_result_storage(tmp_path):
    db_file = tmp_path / "result_storage.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_res_01", initial_status="READY")

    async def mock_process(task_id):
        return "success_metadata_123"

    await agent.start(mock_process)
    await asyncio.sleep(0.3)

    final_status = await agent.get_task_status("t_res_01")
    assert final_status == "COMPLETED"

    conn = sqlite3.connect(agent.db_path)
    try:
        cursor = conn.execute("SELECT result FROM tasks WHERE id = 't_res_01'")
        res = cursor.fetchone()[0]
        assert res == "success_metadata_123"
    finally:
        conn.close()

    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_auto_retry_success(tmp_path):
    db_file = tmp_path / "retry_success.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_retry_01", initial_status="READY", max_retries=2)

    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("Transient error")
        return "finally_success"

    await agent.start(mock_process)
    await asyncio.sleep(0.5)

    final_status = await agent.get_task_status("t_retry_01")
    assert final_status == "COMPLETED"
    assert call_count == 2

    conn = sqlite3.connect(agent.db_path)
    try:
        cursor = conn.execute("SELECT result, retry_count, error FROM tasks WHERE id = 't_retry_01'")
        row = cursor.fetchone()
        assert row[0] == "finally_success"
        assert row[1] == 1
        assert "Transient error" in row[2]
    finally:
        conn.close()

    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_auto_retry_exhausted(tmp_path):
    db_file = tmp_path / "retry_fail.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_retry_02", initial_status="READY", max_retries=1)

    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        raise ValueError(f"Error {call_count}")

    await agent.start(mock_process)
    await asyncio.sleep(0.5)

    final_status = await agent.get_task_status("t_retry_02")
    assert final_status == "FAILED"
    assert call_count == 2

    conn = sqlite3.connect(agent.db_path)
    try:
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = 't_retry_02'")
        row = cursor.fetchone()
        assert row[0] == 1
        assert "Error 2" in row[1]
    finally:
        conn.close()

    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_auto_migration(tmp_path):
    db_file = tmp_path / "migration_test.db"
    
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            stage TEXT,
            status TEXT,
            error TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()

    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()

    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns

    await agent.register_task(task_id="t_mig_01", initial_status="PENDING", max_retries=3)
    status = await agent.get_task_status("t_mig_01")
    assert status == "PENDING"

    await agent.stop()
