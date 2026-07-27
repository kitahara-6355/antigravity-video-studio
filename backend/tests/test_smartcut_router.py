import sys

try:
    import typing
    # Python 3.13 + Pydantic v2 の互換性問題回避パッチ
    # typing.Generic の等価比較を同一性比較 (is) に制限することで、
    # MRO内の他クラス(objectなど)との誤一致を防ぎ、PydanticのMROチェックでの ValueError を回避します。
    typing.Generic.__eq__ = lambda self, other: self is other
except Exception:
    pass

try:
    import pydantic.root_model
except ImportError:
    pass

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from routers.smartcut import router, _get_smart_cut
import routers.smartcut as smartcut_module

# テスト用のFastAPIアプリ作成
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_smart_cut_instance():
    """テストごとにSmartCutインスタンスをリセットする"""
    smartcut_module._smart_cut_instance = None
    yield
    smartcut_module._smart_cut_instance = None


def test_health_check():
    """/health エンドポイントのテスト"""
    response = client.get("/api/smartcut/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "smartcut"}


def test_recommend_not_initialized():
    """初期化前に /recommend を呼び出した場合のエラーハンドリング"""
    response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 15})
    assert response.status_code == 400
    assert "SmartCut not initialized" in response.json()["detail"]


def test_lock_not_initialized():
    """初期化前に /lock を呼び出した場合のエラーハンドリング"""
    response = client.post("/api/smartcut/lock", json={
        "segment_id": "seg_01",
        "title": "Test Locked Segment",
        "start_time": 10.0,
        "end_time": 20.0,
        "reason": "Important scene"
    })
    assert response.status_code == 400
    assert "SmartCut not initialized" in response.json()["detail"]


def test_unlock_not_initialized():
    """初期化前に /unlock を呼び出した場合のエラーハンドリング"""
    response = client.post("/api/smartcut/unlock", json={"segment_id": "seg_01"})
    assert response.status_code == 400
    assert "SmartCut not initialized" in response.json()["detail"]


def test_all_candidates_not_initialized():
    """初期化前に /all-candidates を呼び出した場合のエラーハンドリング"""
    response = client.get("/api/smartcut/all-candidates")
    assert response.status_code == 400
    assert "SmartCut not initialized" in response.json()["detail"]


def test_finalize_not_initialized():
    """初期化前に /finalize を呼び出した場合のエラーハンドリング"""
    response = client.post("/api/smartcut/finalize")
    assert response.status_code == 400
    assert "SmartCut not initialized" in response.json()["detail"]


def test_smartcut_entire_workflow_success():
    """正常系: 初期化から推奨取得、ロック、アンロック、ファイナライズの一連のワークフローが正常に行われることを検証"""
    # 1. /init の呼び出し
    init_req = {
        "segments": [
            {"id": "seg_01", "start": 0.0, "end": 10.0, "text": "This is a highlight scene", "score": 0.9},
            {"id": "seg_02", "start": 10.0, "end": 20.0, "text": "Normal scene", "score": 0.4},
            {"id": "seg_03", "start": 20.0, "end": 30.0, "text": "Another highlight scene", "score": 0.85}
        ],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    }
    
    response = client.post("/api/smartcut/init", json=init_req)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "scan_result" in res_data
    assert "recommendation" in res_data
    
    # 2. /recommend の呼び出し
    recommend_req = {"target_duration_minutes": 30}
    response = client.post("/api/smartcut/recommend", json=recommend_req)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "recommendation" in res_data
    
    # 3. /all-candidates の呼び出し
    response = client.get("/api/smartcut/all-candidates")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "candidates" in res_data
    
    # 4. /lock の呼び出し
    lock_req = {
        "segment_id": "seg_01",
        "title": "Important Hook",
        "start_time": 0.0,
        "end_time": 10.0,
        "reason": "User manual override"
    }
    response = client.post("/api/smartcut/lock", json=lock_req)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert len(res_data["locked_segments"]) == 1
    assert res_data["locked_segments"][0]["id"] == "seg_01"
    
    # 5. /unlock の呼び出し
    unlock_req = {"segment_id": "seg_01"}
    response = client.post("/api/smartcut/unlock", json=unlock_req)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert len(res_data["locked_segments"]) == 0
    
    # 6. /finalize の呼び出し
    response = client.post("/api/smartcut/finalize")
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert "finalized" in res_data


def test_lock_validation_error():
    """LockRequest の start_time >= end_time によるバリデーションエラーのテスト"""
    response = client.post("/api/smartcut/lock", json={
        "segment_id": "seg_01",
        "title": "Invalid Segment",
        "start_time": 20.0,
        "end_time": 10.0,
        "reason": "Invalid time range"
    })
    assert response.status_code == 422


import builtins
real_import = builtins.__import__


def mock_import(name, *args, **kwargs):
    if "lightweight_scan_plugin" in name:
        raise ImportError(f"Mocked import error for {name}")
    return real_import(name, *args, **kwargs)


@patch("plugins.lightweight_scan_plugin.LightweightScanPlugin")
def test_init_http_exception(mock_plugin_cls):
    mock_plugin = mock_plugin_cls.return_value
    mock_plugin.execute.side_effect = HTTPException(status_code=403, detail="Forbidden scan")
    
    response = client.post("/api/smartcut/init", json={
        "segments": [],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    })
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden scan"


def test_init_import_error():
    with patch("builtins.__import__", side_effect=mock_import):
        response = client.post("/api/smartcut/init", json={
            "segments": [],
            "opening_duration": 5.0,
            "ending_duration": 5.0
        })
        assert response.status_code == 500
        assert "Failed to load required plugins" in response.json()["detail"]


@patch("plugins.lightweight_scan_plugin.LightweightScanPlugin")
def test_init_general_exception(mock_plugin_cls):
    mock_plugin = mock_plugin_cls.return_value
    mock_plugin.execute.side_effect = Exception("Something went wrong")
    
    response = client.post("/api/smartcut/init", json={
        "segments": [],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    })
    assert response.status_code == 500
    assert "Something went wrong" in response.json()["detail"]


@patch("plugins.lightweight_scan_plugin.LightweightScanPlugin")
def test_init_value_error(mock_plugin_cls):
    mock_plugin = mock_plugin_cls.return_value
    mock_plugin.execute.side_effect = ValueError("Invalid segments parameter")
    
    response = client.post("/api/smartcut/init", json={
        "segments": [],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    })
    assert response.status_code == 400
    assert "Invalid segments parameter" in response.json()["detail"]


def test_recommend_exceptions():
    smart_cut_mock = MagicMock()
    smart_cut_mock._context = MagicMock()
    
    with patch("routers.smartcut._get_smart_cut", return_value=smart_cut_mock):
        # 1. HTTPException
        smart_cut_mock.update_recommendation.side_effect = HTTPException(status_code=402, detail="Payment Required")
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 402
        
        # 2. ImportError
        smart_cut_mock.update_recommendation.side_effect = ImportError("Missing library")
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 500
        assert "Failed to load required plugins" in response.json()["detail"]
        
        # 3. General Exception
        smart_cut_mock.update_recommendation.side_effect = Exception("General error")
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 500
        assert "General error" in response.json()["detail"]

        # 4. ValueError
        smart_cut_mock.update_recommendation.side_effect = ValueError("Value error recommendation")
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 400
        assert "Value error recommendation" in response.json()["detail"]


def test_lock_exceptions():
    smart_cut_mock = MagicMock()
    smart_cut_mock._context = MagicMock()
    
    with patch("routers.smartcut._get_smart_cut", return_value=smart_cut_mock):
        req_data = {
            "segment_id": "seg_01",
            "title": "Hook",
            "start_time": 0.0,
            "end_time": 10.0
        }
        
        # 1. HTTPException
        smart_cut_mock.lock_segment.side_effect = HTTPException(status_code=402, detail="Lock failed")
        response = client.post("/api/smartcut/lock", json=req_data)
        assert response.status_code == 402
        
        # 2. ImportError
        smart_cut_mock.lock_segment.side_effect = ImportError("Missing library")
        response = client.post("/api/smartcut/lock", json=req_data)
        assert response.status_code == 500
        
        # 3. General Exception
        smart_cut_mock.lock_segment.side_effect = Exception("General error")
        response = client.post("/api/smartcut/lock", json=req_data)
        assert response.status_code == 500

        # 4. ValueError
        smart_cut_mock.lock_segment.side_effect = ValueError("Value error lock")
        response = client.post("/api/smartcut/lock", json=req_data)
        assert response.status_code == 400
        assert "Value error lock" in response.json()["detail"]


def test_unlock_exceptions():
    smart_cut_mock = MagicMock()
    smart_cut_mock._context = MagicMock()
    
    with patch("routers.smartcut._get_smart_cut", return_value=smart_cut_mock):
        req_data = {"segment_id": "seg_01"}
        
        # 1. HTTPException
        smart_cut_mock.unlock_segment.side_effect = HTTPException(status_code=402, detail="Unlock failed")
        response = client.post("/api/smartcut/unlock", json=req_data)
        assert response.status_code == 402
        
        # 2. ImportError
        smart_cut_mock.unlock_segment.side_effect = ImportError("Missing library")
        response = client.post("/api/smartcut/unlock", json=req_data)
        assert response.status_code == 500
        
        # 3. General Exception
        smart_cut_mock.unlock_segment.side_effect = Exception("General error")
        response = client.post("/api/smartcut/unlock", json=req_data)
        assert response.status_code == 500

        # 4. ValueError
        smart_cut_mock.unlock_segment.side_effect = ValueError("Value error unlock")
        response = client.post("/api/smartcut/unlock", json=req_data)
        assert response.status_code == 400
        assert "Value error unlock" in response.json()["detail"]


def test_all_candidates_exceptions():
    smart_cut_mock = MagicMock()
    smart_cut_mock._context = MagicMock()
    
    with patch("routers.smartcut._get_smart_cut", return_value=smart_cut_mock):
        # 1. HTTPException
        smart_cut_mock.get_all_candidates.side_effect = HTTPException(status_code=402, detail="Candidates failed")
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 402
        
        # 2. ImportError
        smart_cut_mock.get_all_candidates.side_effect = ImportError("Missing library")
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 500
        
        # 3. General Exception
        smart_cut_mock.get_all_candidates.side_effect = Exception("General error")
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 500

        # 4. ValueError
        smart_cut_mock.get_all_candidates.side_effect = ValueError("Value error candidates")
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 400
        assert "Value error candidates" in response.json()["detail"]


def test_finalize_exceptions():
    smart_cut_mock = MagicMock()
    smart_cut_mock._context = MagicMock()
    
    with patch("routers.smartcut._get_smart_cut", return_value=smart_cut_mock):
        # 1. HTTPException
        smart_cut_mock.finalize.side_effect = HTTPException(status_code=402, detail="Finalize failed")
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 402
        
        # 2. ImportError
        smart_cut_mock.finalize.side_effect = ImportError("Missing library")
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 500
        
        # 3. General Exception
        smart_cut_mock.finalize.side_effect = Exception("General error")
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 500

        # 4. ValueError
        smart_cut_mock.finalize.side_effect = ValueError("Value error finalize")
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 400
        assert "Value error finalize" in response.json()["detail"]


import sqlite3

@pytest.mark.asyncio
async def test_thumbnail_success():
    from unittest.mock import AsyncMock
    mock_agent_instance = MagicMock()
    mock_agent_instance.register_task = AsyncMock()
    mock_agent_instance.start = AsyncMock()
    mock_agent_instance.get_task_status = AsyncMock(side_effect=["COMPLETED", "COMPLETED"])
    mock_agent_instance.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ['{"width": 1280, "height": 720, "path": "some/path.png"}']
    mock_conn.execute.return_value = mock_cursor
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent_instance), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("services.smartcut_strategy_service.SmartCutStrategyService") as mock_service_cls:
        
        mock_service = mock_service_cls.return_value
        
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123",
            "width": 1280,
            "height": 720,
            "text": "My custom thumbnail"
        })
        
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["success"] is True
        assert res_data["status"] == "COMPLETED"
        assert res_data["thumbnail"]["width"] == 1280


@pytest.mark.asyncio
async def test_thumbnail_sqlite_error():
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mock SQLite Error")):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 500
        assert "Database error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_import_error():
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=ImportError("Mocked import error for stage_bound_agent"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect"):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 500
        assert "Required module not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_http_exception():
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=HTTPException(status_code=400, detail="Custom HTTP error"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 400
        assert response.json()["detail"] == "Custom HTTP error"


@pytest.mark.asyncio
async def test_thumbnail_task_failed_exception():
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.get_task_status = AsyncMock(return_value="FAILED")
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.execute.return_value = mock_cursor
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 500
        assert "Thumbnail task failed with status FAILED" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_value_error_exception():
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=ValueError("Invalid config parameter"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect"):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 400
        assert "Invalid config parameter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_type_error_in_json_loads():
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.get_task_status = AsyncMock(return_value="FAILED")
    mock_agent.stop = AsyncMock()

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ["invalid-json-string"]
    mock_conn.execute.return_value = mock_cursor

    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 500
        assert "Thumbnail task failed: invalid-json-string" in response.json()["detail"]


def test_init_validation_error():
    """InitRequest のバリデーションエラー (segments 欠損) による 422 Unprocessable Entity のテスト"""
    response = client.post("/api/smartcut/init", json={
        "opening_duration": 5.0,
        "ending_duration": 5.0
    })
    assert response.status_code == 422


@patch("routers.smartcut.logger")
@patch("plugins.lightweight_scan_plugin.LightweightScanPlugin")
def test_init_exception_logging(mock_plugin_cls, mock_logger):
    """一般例外発生時に logger.exception が正しく呼び出されることを検証"""
    mock_plugin = mock_plugin_cls.return_value
    mock_plugin.execute.side_effect = Exception("Fatal Scan Failure")
    
    response = client.post("/api/smartcut/init", json={
        "segments": [],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    })
    assert response.status_code == 500
    mock_logger.exception.assert_called_with("SmartCut init failed")


def test_lock_already_locked():
    """同じセグメントを2回ロックした場合に 400 Bad Request を返すことを検証"""
    # 1. /init の呼び出し
    init_req = {
        "segments": [
            {"id": "seg_01", "start": 0.0, "end": 10.0, "text": "Highlight scene", "score": 0.9}
        ]
    }
    response = client.post("/api/smartcut/init", json=init_req)
    assert response.status_code == 200

    # 2. 1回目のロック
    lock_req = {
        "segment_id": "seg_01",
        "title": "First Lock",
        "start_time": 0.0,
        "end_time": 10.0,
        "reason": "Test lock"
    }
    response = client.post("/api/smartcut/lock", json=lock_req)
    assert response.status_code == 200

    # 3. 2回目のロック（同じセグメント）
    response2 = client.post("/api/smartcut/lock", json=lock_req)
    assert response2.status_code == 400
    assert "already locked" in response2.json()["detail"]


def test_unlock_not_found():
    """ロックされていないセグメントをアンロックしようとした場合に 404 Not Found を返すことを検証"""
    # 1. /init の呼び出し
    init_req = {
        "segments": [
            {"id": "seg_01", "start": 0.0, "end": 10.0, "text": "Highlight scene", "score": 0.9}
        ]
    }
    response = client.post("/api/smartcut/init", json=init_req)
    assert response.status_code == 200

    # 2. アンロックを試みる（ロックされていないセグメント）
    response = client.post("/api/smartcut/unlock", json={"segment_id": "non_existent"})
    assert response.status_code == 404
    assert "Locked segment not found" in response.json()["detail"]


def test_init_invalid_segments():
    """/init において segments のデータ構造が不正な場合に 422 Unprocessable Entity を返すことを検証"""
    # start_time >= end_time の場合
    init_req_invalid_time = {
        "segments": [
            {"id": "seg_01", "start": 10.0, "end": 5.0, "text": "Invalid time scene"}
        ]
    }
    response = client.post("/api/smartcut/init", json=init_req_invalid_time)
    assert response.status_code == 422

    # start_time < 0 の場合
    init_req_negative_time = {
        "segments": [
            {"id": "seg_01", "start": -1.0, "end": 10.0, "text": "Negative time scene"}
        ]
    }
    response = client.post("/api/smartcut/init", json=init_req_negative_time)
    assert response.status_code == 422


def test_init_automatic_segment_id_assignment():
    """IDが欠落したセグメントに対して自動的に一意のIDが割り当てられることを検証"""
    init_req = {
        "segments": [
            {"start": 0.0, "end": 10.0, "text": "No ID segment 1"},
            {"start": 10.0, "end": 20.0, "text": "No ID segment 2"}
        ],
        "opening_duration": 5.0,
        "ending_duration": 5.0
    }
    
    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin") as mock_scan_plugin_cls, \
         patch("plugins.smart_cut_plugin.SmartCutPlugin") as mock_smart_cut_plugin_cls:
        
        mock_scan_plugin = mock_scan_plugin_cls.return_value
        mock_context = MagicMock()
        mock_scan_result = MagicMock()
        mock_scan_result.total_segments = 2
        mock_scan_result.highlight_candidates = []
        mock_scan_result.chapter_candidates = []
        mock_scan_result.estimated_cut_rate = 0.5
        mock_context.scan_result = mock_scan_result
        mock_scan_plugin.execute.return_value = mock_context
        
        mock_smart_cut = mock_smart_cut_plugin_cls.return_value
        mock_smart_cut.get_recommendation.return_value = {}
        
        response = client.post("/api/smartcut/init", json=init_req)
        assert response.status_code == 200
        
        called_context = mock_scan_plugin.execute.call_args[0][0]
        assert len(called_context.segments) == 2
        assert called_context.segments[0]["id"] == "seg_auto_0_0_10"
        assert called_context.segments[1]["id"] == "seg_auto_1_10_20"


def test_lock_request_empty_fields_validation_error():
    """LockRequest の segment_id や title が空文字の場合に 422 Unprocessable Entity を返すことを検証"""
    response = client.post("/api/smartcut/lock", json={
        "segment_id": "",
        "title": "Valid Title",
        "start_time": 0.0,
        "end_time": 10.0,
        "reason": "Test"
    })
    assert response.status_code == 422

    response = client.post("/api/smartcut/lock", json={
        "segment_id": "seg_01",
        "title": "",
        "start_time": 0.0,
        "end_time": 10.0,
        "reason": "Test"
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_thumbnail_os_error_handling():
    """os.makedirs で OSError が発生した場合に 500 Internal Server Error が返ることを検証"""
    with patch("os.makedirs", side_effect=OSError("Disk Full or Permission Denied")):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123",
            "width": 1280,
            "height": 720,
            "text": "Failed Thumbnail"
        })
        assert response.status_code == 500



def test_init_type_error():
    """/init で TypeError が発生した場合に 400 Bad Request を返すことを検証"""
    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin") as mock_scan_plugin_cls:
        mock_plugin = mock_scan_plugin_cls.return_value
        mock_plugin.execute.side_effect = TypeError("Invalid argument types passed to plugin")
        
        response = client.post("/api/smartcut/init", json={
            "segments": [],
            "opening_duration": 5.0,
            "ending_duration": 5.0
        })
        assert response.status_code == 400
        assert "Invalid parameter types" in response.json()["detail"]


def test_init_key_error():
    """/init で KeyError が発生した場合に 400 Bad Request を返すことを検証"""
    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin") as mock_scan_plugin_cls:
        mock_plugin = mock_scan_plugin_cls.return_value
        mock_plugin.execute.side_effect = KeyError("missing_config_key")
        
        response = client.post("/api/smartcut/init", json={
            "segments": [],
            "opening_duration": 5.0,
            "ending_duration": 5.0
        })
        assert response.status_code == 400
        assert "Missing expected key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_type_error_handling():
    """/api/smartcut/thumbnail で TypeError が発生した場合に 400 Bad Request が返ることを検証"""
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=TypeError("Mocked Type Error"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect"):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 400
        assert "Type error: Mocked Type Error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_key_error_handling():
    """/api/smartcut/thumbnail で KeyError が発生した場合に 400 Bad Request が返ることを検証"""
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=KeyError("Mocked Key Error"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect"):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 400
        assert "Missing key: 'Mocked Key Error'" in response.json()["detail"]


@pytest.mark.asyncio
async def test_thumbnail_general_os_error_handling():
    """/api/smartcut/thumbnail の実行中に OSError が発生した場合に 500 が返ることを検証"""
    from unittest.mock import AsyncMock
    mock_agent = MagicMock()
    mock_agent.register_task = AsyncMock(side_effect=OSError("Mocked OSError during execution"))
    mock_agent.stop = AsyncMock()
    
    with patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect"):
        response = client.post("/api/smartcut/thumbnail", json={
            "session_id": "session_123",
            "task_id": "task_123"
        })
        assert response.status_code == 500
        assert "OS error: Mocked OSError during execution" in response.json()["detail"]



