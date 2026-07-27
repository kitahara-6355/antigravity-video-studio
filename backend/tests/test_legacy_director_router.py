import pytest
import os
import json
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, mock_open

# パス追加
import sys
from pathlib import Path
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from routers.legacy_director_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_asyncio_to_thread():
    """asyncio.to_thread を同期実行にモック化し、別スレッドでのモック競合を防止する"""
    import asyncio
    from unittest.mock import patch
    
    async def dummy_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)
        
    with patch("asyncio.to_thread", side_effect=dummy_to_thread):
        yield


# 1. GET /api/director/tasks/{task_id}
@patch("routers.legacy_director_router.task_manager.get_task")
def test_get_director_task_status_success(mock_get_task):
    mock_get_task.return_value = {"id": "task-123", "status": "completed"}
    response = client.get("/api/director/tasks/task-123")
    assert response.status_code == 200
    assert response.json() == {"id": "task-123", "status": "completed"}
    mock_get_task.assert_called_once_with("task-123")

@patch("routers.legacy_director_router.task_manager.get_task")
def test_get_director_task_status_not_found(mock_get_task):
    mock_get_task.return_value = None
    response = client.get("/api/director/tasks/task-999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
    mock_get_task.assert_called_once_with("task-999")

# 2. GET /api/director/state
@patch("routers.legacy_director_router.os.path.exists")
def test_get_director_state_not_exists(mock_exists):
    mock_exists.return_value = False
    response = client.get("/api/director/state")
    assert response.status_code == 200
    assert response.json() == {"scenes": [], "audioConfig": None}

@patch("routers.legacy_director_router.os.path.exists")
def test_get_director_state_success(mock_exists):
    mock_exists.return_value = True
    mock_data = {"scenes": [{"id": 1}], "audioConfig": {"volume": 0.8}}
    
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
        response = client.get("/api/director/state")
        assert response.status_code == 200
        assert response.json() == mock_data

@patch("routers.legacy_director_router.os.path.exists")
def test_get_director_state_json_error(mock_exists):
    mock_exists.return_value = True
    # 壊れたJSONデータを返す
    with patch("builtins.open", mock_open(read_data="{invalid_json}")):
        response = client.get("/api/director/state")
        assert response.status_code == 200
        assert response.json() == {"scenes": [], "audioConfig": None}

@patch("routers.legacy_director_router.os.path.exists")
def test_get_director_state_http_exception(mock_exists):
    mock_exists.return_value = True
    with patch("builtins.open", side_effect=HTTPException(status_code=400, detail="Mock HTTP Exception")):
        response = client.get("/api/director/state")
        assert response.status_code == 400
        assert response.json()["detail"] == "Mock HTTP Exception"

# 3. POST /api/director/state
@patch("project_archiver.project_archiver.save_snapshot")
def test_save_director_state_success(mock_save_snapshot):
    mock_data = {"scenes": [{"id": 1}], "audioConfig": {"volume": 0.8}}
    
    m_open = mock_open()
    with patch("builtins.open", m_open):
        response = client.post("/api/director/state", json=mock_data)
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        
        mock_save_snapshot.assert_called_once_with(label="auto_before_save")
        # 書き込み内容の検証
        written_data = "".join(call.args[0] for call in m_open().write.call_args_list)
        assert json.loads(written_data) == mock_data

@patch("project_archiver.project_archiver.save_snapshot")
def test_save_director_state_error(mock_save_snapshot):
    mock_save_snapshot.side_effect = OSError("Disk full")
    response = client.post("/api/director/state", json={})
    assert response.status_code == 500
    assert "Disk full" in response.json()["detail"]

@patch("project_archiver.project_archiver.save_snapshot")
def test_save_director_state_uncaught_exception(mock_save_snapshot):
    mock_save_snapshot.side_effect = Exception("Uncaught generic exception")
    with pytest.raises(Exception) as exc_info:
        client.post("/api/director/state", json={})
    assert "Uncaught generic exception" in str(exc_info.value)

@patch("project_archiver.project_archiver.save_snapshot")
def test_save_director_state_http_exception(mock_save_snapshot):
    mock_save_snapshot.side_effect = HTTPException(status_code=400, detail="Snapshot HTTP error")
    response = client.post("/api/director/state", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "Snapshot HTTP error"

# 4. POST /api/director/verify-quality
@patch("routers.legacy_director_router.brain.verify_production_quality")
def test_verify_quality_success(mock_verify):
    mock_result = {"passed": True, "score": 95}
    mock_verify.return_value = json.dumps(mock_result)
    
    req_body = {
        "full_text": "sample text",
        "scenes": [{"id": 1}],
        "segments": [{"id": 2}]
    }
    response = client.post("/api/director/verify-quality", json=req_body)
    assert response.status_code == 200
    assert response.json() == mock_result
    mock_verify.assert_called_once_with("sample text", [{"id": 1}], [{"id": 2}])

@patch("routers.legacy_director_router.brain.verify_production_quality")
def test_verify_quality_error(mock_verify):
    mock_verify.side_effect = RuntimeError("Brain offline")
    response = client.post("/api/director/verify-quality", json={})
    assert response.status_code == 500
    assert "Brain offline" in response.json()["detail"]

@patch("routers.legacy_director_router.brain.verify_production_quality")
def test_verify_quality_uncaught_exception(mock_verify):
    mock_verify.side_effect = Exception("Uncaught generic exception")
    with pytest.raises(Exception) as exc_info:
        client.post("/api/director/verify-quality", json={})
    assert "Uncaught generic exception" in str(exc_info.value)

@patch("routers.legacy_director_router.brain.verify_production_quality")
def test_verify_quality_http_exception(mock_verify):
    mock_verify.side_effect = HTTPException(status_code=400, detail="Brain HTTP error")
    response = client.post("/api/director/verify-quality", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "Brain HTTP error"

# 5. GET /api/director/evolution
@patch("routers.legacy_director_router.branding_manager.get_evolution_log")
def test_get_evolution(mock_get_log):
    mock_log = [{"event": "growth"}]
    mock_get_log.return_value = mock_log
    response = client.get("/api/director/evolution")
    assert response.status_code == 200
    assert response.json() == mock_log
    mock_get_log.assert_called_once()

# 6. GET /api/director/profile
@patch("decision_logger.decision_logger.get_director_preferences")
def test_get_director_profile(mock_get_prefs):
    mock_prefs = {"preference": "high_contrast"}
    mock_get_prefs.return_value = mock_prefs
    response = client.get("/api/director/profile")
    assert response.status_code == 200
    assert response.json() == mock_prefs
    mock_get_prefs.assert_called_once()


# 7. Malformed JSON Test cases for coverage
def test_save_director_state_malformed_json():
    response = client.post(
        "/api/director/state",
        content="invalid json",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Malformed JSON" in response.json()["detail"]

def test_verify_quality_malformed_json():
    response = client.post(
        "/api/director/verify-quality",
        content="invalid json",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "Malformed JSON" in response.json()["detail"]


def test_scenes_path_resolution():
    from routers.legacy_director_router import SCENES_PATH
    # SCENES_PATH が backend/src ではなく、プロジェクトルートの src/scenes_data.json であることを検証
    assert "backend/src" not in SCENES_PATH.replace("\\", "/")
    assert SCENES_PATH.endswith("src/scenes_data.json") or SCENES_PATH.endswith("src\\scenes_data.json")


@pytest.mark.asyncio
async def test_asyncio_to_thread_mocked():
    import asyncio
    
    called = False
    def target_func():
        nonlocal called
        called = True
        return "success"
        
    res = await asyncio.to_thread(target_func)
    assert res == "success"
    assert called is True
