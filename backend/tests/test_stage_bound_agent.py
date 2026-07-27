# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import pytest
import sys
from unittest.mock import MagicMock

# Heavy Google GenAI / Pydantic import bypass for test reliability on Windows/Python3.13
mock_google = MagicMock()
mock_genai = MagicMock()
mock_types = MagicMock()
mock_client_inst = MagicMock()
mock_genai.Client.return_value = mock_client_inst
mock_google.genai = mock_genai
sys.modules["google"] = mock_google
sys.modules["google.genai"] = mock_genai
sys.modules["google.genai.types"] = mock_types

# ImageFont.truetype import bypass for test reliability and speed
from PIL import ImageFont
original_truetype = ImageFont.truetype

def mock_truetype(font, size=10, index=0, encoding="", layout_engine=None):
    font_str = str(font).lower() if font else ""
    heavy_fonts = ["msjh", "meiryo", "yugoth", "msgothic", "msmincho", "pingfang", "hiragino", "notosans", "cjk"]
    if font and any(jf in font_str for jf in heavy_fonts):
        font = "arial.ttf"
    try:
        return original_truetype(font, size, index, encoding, layout_engine)
    except Exception:
        try:
            return original_truetype("arial.ttf", size, index, encoding, layout_engine)
        except Exception:
            return original_truetype(None, size, index, encoding, layout_engine)

ImageFont.truetype = mock_truetype

from backend.agents.stage_bound_agent import StageBoundAgent

@pytest.mark.asyncio
async def test_stage_bound_agent_success(tmp_path):
    db_file = tmp_path / "success.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    await agent.register_task(task_id="t_001", initial_status="PENDING")
    
    status = await agent.get_task_status("t_001")
    assert status == "PENDING"

    assert agent._fetch_ready_task() is None

    agent._update_task_status("t_001", "READY")
    
    ready_task = agent._fetch_ready_task()
    assert ready_task is not None
    assert ready_task["id"] == "t_001"

    executed_task_id = None
    async def mock_process(task_id):
        nonlocal executed_task_id
        executed_task_id = task_id
        await asyncio.sleep(0.05)

    await agent.start(mock_process)
    await asyncio.sleep(0.3)
    
    assert executed_task_id == "t_001"
    
    final_status = await agent.get_task_status("t_001")
    assert final_status == "COMPLETED"
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_failure(tmp_path):
    db_file = tmp_path / "failure.db"
    agent = StageBoundAgent(stage_name="telop", db_path=str(db_file))
    await agent.register_task(task_id="t_002", initial_status="READY")

    def failing_process(task_id):
        raise RuntimeError("FFmpeg format error")

    await agent.start(failing_process)
    await asyncio.sleep(0.3)

    final_status = await agent.get_task_status("t_002")
    assert final_status == "FAILED"
    
    conn = sqlite3.connect(agent.db_path)
    try:
        cursor = conn.execute("SELECT error FROM tasks WHERE id = 't_002'")
        error_msg = cursor.fetchone()[0]
        assert "FFmpeg format error" in error_msg
    finally:
        conn.close()

    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_success(tmp_path):
    db_file = tmp_path / "llm_success.db"
    from backend.model_governance_local import LocalAsyncGateway
    
    async def mock_client_call(model, prompt, config):
        await asyncio.sleep(0.01)
        return f"Mocked response for prompt: {prompt}"
        
    gateway = LocalAsyncGateway(db_path=str(db_file))
    await gateway.start(mock_client_call)
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), gateway=gateway)
    
    response = await agent.call_llm(prompt="Hello", model="gemini-2.5-flash")
    assert response == "Mocked response for prompt: Hello"
    
    await agent.stop()
    await gateway.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_own_gateway(tmp_path):
    db_file = tmp_path / "llm_own.db"
    from unittest.mock import patch, MagicMock
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    mock_response = MagicMock()
    mock_response.text = "Own gateway mocked response"
    
    with patch("google.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        response = await agent.call_llm(prompt="Hello Own", model="gemini-2.5-flash")
        assert response == "Own gateway mocked response"
        
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_failure(tmp_path):
    db_file = tmp_path / "llm_fail.db"
    from backend.model_governance_local import LocalAsyncGateway
    
    async def mock_client_fail(model, prompt, config):
        raise RuntimeError("API quota exceeded")
        
    gateway = LocalAsyncGateway(db_path=str(db_file))
    await gateway.start(mock_client_fail)
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), gateway=gateway)
    
    with pytest.raises(RuntimeError) as exc_info:
        await agent.call_llm(prompt="Hello Fail", model="gemini-2.5-flash")
    assert "API quota exceeded" in str(exc_info.value)
    
    await agent.stop()
    await gateway.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_memory_db_and_close_error():
    # 1. :memory: の cached_conn テスト
    agent = StageBoundAgent(stage_name="memory_test", db_path=":memory:")
    conn1 = agent._get_conn()
    conn2 = agent._get_conn()
    assert conn1 is conn2  # cached_conn が同じであることを確認
    
    # 元の接続を明示的に閉じて ResourceWarning を防ぐ
    conn1.close()
    
    # 2. sqlite3.Error 例外安全ハンドリングのテスト
    from unittest.mock import MagicMock
    mock_conn = MagicMock()
    mock_conn.close.side_effect = sqlite3.Error("Mocked sqlite3 error")
    agent._cached_conn = mock_conn
    
    # 例外がキャッチされて安全に stop() が完了することを確認
    await agent.stop()
    assert agent._cached_conn is None


@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_default_client_failure(tmp_path):
    db_file = tmp_path / "llm_default_fail.db"
    from unittest.mock import patch, MagicMock
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    with patch("google.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Default client exception")
        mock_client_class.return_value = mock_client
        
        with pytest.raises(Exception) as exc_info:
            await agent.call_llm(prompt="Hello Exception", model="gemini-2.5-flash")
        assert "Default client exception" in str(exc_info.value)
        
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_job_not_found(tmp_path):
    db_file = tmp_path / "llm_not_found.db"
    from backend.model_governance_local import LocalAsyncGateway
    from unittest.mock import patch
    
    gateway = LocalAsyncGateway(db_path=str(db_file))
    async def mock_client_call(model, prompt, config):
        return "OK"
    await gateway.start(mock_client_call)
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), gateway=gateway)
    
    # get_job をモックして None を返すようにする
    with patch.object(gateway, "get_job", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            await agent.call_llm(prompt="Hello Missing", model="gemini-2.5-flash")
        assert "not found in gateway" in str(exc_info.value)
        
    await agent.stop()
    await gateway.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_get_task_status_none(tmp_path):
    db_file = tmp_path / "status_none.db"
    agent = StageBoundAgent(stage_name="telop", db_path=str(db_file))
    
    status = await agent.get_task_status("non_existent_task")
    assert status is None
    
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_failure_async(tmp_path):
    db_file = tmp_path / "failure_async.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    await agent.register_task(task_id="t_003", initial_status="READY")

    async def failing_process_async(task_id):
        raise RuntimeError("Async process failure")

    await agent.start(failing_process_async)
    await asyncio.sleep(0.3)

    final_status = await agent.get_task_status("t_003")
    assert final_status == "FAILED"
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_poll_loop_db_error_recovery(tmp_path):
    db_file = tmp_path / "db_err_recovery.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    await agent.register_task(task_id="t_004", initial_status="READY")

    original_fetch = agent._fetch_ready_task
    call_count = 0

    def mock_fetch():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_fetch()

    agent._fetch_ready_task = mock_fetch

    executed = False
    async def mock_process(task_id):
        nonlocal executed
        executed = True

    await agent.start(mock_process)
    await asyncio.sleep(0.5)

    assert executed is True
    final_status = await agent.get_task_status("t_004")
    assert final_status == "COMPLETED"
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_default_client_import_error(tmp_path):
    import sys
    db_file = tmp_path / "import_err.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))

    real_google = sys.modules.get("google")
    real_google_genai = sys.modules.get("google.genai")

    sys.modules["google"] = None
    sys.modules["google.genai"] = None

    try:
        with pytest.raises(Exception) as exc_info:
            await agent.call_llm(prompt="Hello", model="gemini-2.5-flash")
        assert "import of google" in str(exc_info.value)
    finally:
        if real_google is not None:
            sys.modules["google"] = real_google
        else:
            sys.modules.pop("google", None)
        if real_google_genai is not None:
            sys.modules["google.genai"] = real_google_genai
        else:
            sys.modules.pop("google.genai", None)

    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_gateway_enqueue_failure(tmp_path):
    db_file = tmp_path / "enqueue_fail.db"
    from backend.model_governance_local import LocalAsyncGateway
    from unittest.mock import AsyncMock

    gateway = LocalAsyncGateway(db_path=str(db_file))
    gateway.enqueue_job = AsyncMock(side_effect=Exception("Enqueue failed"))

    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), gateway=gateway)

    with pytest.raises(Exception) as exc_info:
        await agent.call_llm(prompt="Hello", model="gemini-2.5-flash")
    assert "Enqueue failed" in str(exc_info.value)

    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_multiple_start(tmp_path):
    db_file = tmp_path / "multistart.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    await agent.register_task(task_id="t_005", initial_status="READY")

    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)

    # 1回目のスタート
    await agent.start(mock_process)
    task1 = agent._poll_task
    
    # 2回目のスタート
    await agent.start(mock_process)
    task2 = agent._poll_task
    
    # 同一タスクであることを検証（多重起動が無視されている）
    assert task1 is task2
    
    await asyncio.sleep(0.2)
    assert call_count == 1
    
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_call_llm_timeout(tmp_path):
    db_file = tmp_path / "llm_timeout.db"
    from backend.model_governance_local import LocalAsyncGateway
    from unittest.mock import AsyncMock, patch
    
    gateway = LocalAsyncGateway(db_path=str(db_file))
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), gateway=gateway)
    
    with patch.object(gateway, "enqueue_job", new_callable=AsyncMock) as mock_enqueue,          patch.object(gateway, "get_job", new_callable=AsyncMock) as mock_get_job:
        
        mock_enqueue.return_value = "job_test_timeout"
        mock_get_job.return_value = {"status": "PENDING"}
        
        # 0.1秒でタイムアウトさせ、適切に RuntimeError が発生することを確認
        with pytest.raises(RuntimeError) as exc_info:
            await agent.call_llm(prompt="Hello", model="gemini-2.5-flash", timeout=0.1)
            
        assert "timed out after 0.1 seconds" in str(exc_info.value)
        
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_stop_idempotency(tmp_path):
    db_file = tmp_path / "idempotency.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    # 起動していない状態で stop()
    await agent.stop()
    
    # 起動した後に stop() を連続実行
    async def mock_process(task_id):
        pass
    await agent.start(mock_process)
    await agent.stop()
    await agent.stop()  # 2回目
    assert agent._poll_task is None


@pytest.mark.asyncio
async def test_stage_bound_agent_duplicate_register(tmp_path):
    db_file = tmp_path / "duplicate.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    await agent.register_task(task_id="dup_task")
    with pytest.raises(sqlite3.IntegrityError):
        await agent.register_task(task_id="dup_task")
        
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_fetch_task_db_error(tmp_path):
    db_file = tmp_path / "fetch_err.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    from unittest.mock import patch
    with patch.object(agent, "_get_conn", side_effect=sqlite3.Error("Mocked fetch conn error")):
        with pytest.raises(sqlite3.Error) as exc_info:
            agent._fetch_ready_task()
        assert "Mocked fetch conn error" in str(exc_info.value)
        
    await agent.stop()


def test_generate_thumbnail_success(tmp_path):
    from backend.agents.stage_bound_agent import generate_thumbnail, validate_thumbnail
    output_path = tmp_path / "thumbnail_ok.png"
    
    res_path = generate_thumbnail(output_path, width=1280, height=720, text="Test Thumbnail")
    assert res_path.exists()
    
    # 品質検証
    info = validate_thumbnail(res_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] < 4 * 1024 * 1024


def test_generate_thumbnail_invalid_resolution(tmp_path):
    from backend.agents.stage_bound_agent import generate_thumbnail
    output_path = tmp_path / "thumbnail_invalid_res.png"
    
    with pytest.raises(ValueError) as exc_info:
        generate_thumbnail(output_path, width=1024, height=720, text="Too Small")
    assert "Resolution must be at least 1280x720" in str(exc_info.value)


def test_generate_thumbnail_invalid_aspect_ratio(tmp_path):
    from backend.agents.stage_bound_agent import generate_thumbnail
    output_path = tmp_path / "thumbnail_invalid_ratio.png"
    
    with pytest.raises(ValueError) as exc_info:
        generate_thumbnail(output_path, width=1280, height=1024, text="Wrong Ratio")
    assert "Aspect ratio must be 16:9" in str(exc_info.value)


def test_validate_thumbnail_corrupted(tmp_path):
    from backend.agents.stage_bound_agent import validate_thumbnail
    
    # 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "non_existent.png")
        
    # 破損したファイル (空ファイル)
    corrupted_path = tmp_path / "corrupted.png"
    corrupted_path.write_bytes(b"invalid data")
    
    with pytest.raises(ValueError) as exc_info:
        validate_thumbnail(corrupted_path)
    assert "Image is corrupted or invalid format" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_success(tmp_path):
    import json
    from backend.agents.stage_bound_agent import resolve_thumbnail_task
    
    class DummyAgent:
        def __init__(self):
            self.output_dir = str(tmp_path)
            self.width = 1280
            self.height = 720
            self.text = "Async Test"
            
    dummy_self = DummyAgent()
    task_id = "test_task_001"
    
    result_str = await resolve_thumbnail_task(dummy_self, task_id)
    result_info = json.loads(result_str)
    
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert "test_task_001.png" in result_info["path"]


@pytest.mark.asyncio
async def test_stage_bound_agent_default_client_runtime_error_wrap(tmp_path):
    db_file = tmp_path / "llm_wrap_fail.db"
    from unittest.mock import patch, MagicMock
    
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file))
    
    with patch("google.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Original root cause")
        mock_client_class.return_value = mock_client
        
        with pytest.raises(RuntimeError) as exc_info:
            await agent.call_llm(prompt="Hello wrap", model="gemini-2.5-flash")
        
        assert "Default client call failed" in str(exc_info.value)
        assert "Original root cause" in str(exc_info.value)
        
    await agent.stop()


@pytest.mark.asyncio
async def test_stage_bound_agent_retry_logic(tmp_path):
    db_file = tmp_path / "retry.db"
    agent = StageBoundAgent(stage_name="smartcut", db_path=str(db_file), poll_interval=0.05)
    
    # max_retries=2 でタスク登録
    await agent.register_task(task_id="t_retry", initial_status="READY", max_retries=2)
    
    call_count = 0
    def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"Retry failure {call_count}")
        
    await agent.start(mock_process)
    
    # 最終ステータスが FAILED になるのを最大 2 秒間待つ
    final_status = None
    for _ in range(20):
        final_status = await agent.get_task_status("t_retry")
        if final_status == "FAILED":
            break
        await asyncio.sleep(0.1)
        
    assert final_status == "FAILED"
    
    # 実行回数が 3 回（初回 + リトライ2回）であることを検証
    assert call_count == 3
    
    # DB 内の retry_count が 2 に更新されていることを検証
    conn = sqlite3.connect(agent.db_path)
    try:
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = 't_retry'")
        row = cursor.fetchone()
        assert row[0] == 2
        assert "Retry failure 3" in row[1]
    finally:
        conn.close()
        
    await agent.stop()


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_default_fallback():
    import json
    import shutil
    from pathlib import Path
    from backend.agents.stage_bound_agent import resolve_thumbnail_task
    
    class EmptyAgent:
        pass
        
    dummy_self = EmptyAgent()
    task_id = "default_fallback_task"
    
    # デフォルトの出力先ディレクトリをあらかじめクリーンアップ
    default_dir = Path("backend/temp_thumbnails")
    if default_dir.exists():
        try:
            shutil.rmtree(default_dir)
        except OSError:
            pass
            
    try:
        result_str = await resolve_thumbnail_task(dummy_self, task_id)
        result_info = json.loads(result_str)
        
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert default_dir.exists()
        assert (default_dir / f"{task_id}.png").exists()
    finally:
        if default_dir.exists():
            try:
                shutil.rmtree(default_dir)
            except OSError:
                pass



