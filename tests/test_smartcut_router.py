import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
import json
import sqlite3

from routers.smartcut import (
    router,
    InitRequest,
    RecommendRequest,
    LockRequest,
    UnlockRequest,
    SmartCutThumbnailRequest,
    _get_smart_cut
)

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# ------------------------------------------------------------
# Test Cases
# ------------------------------------------------------------

def test_health():
    """GET /health エンドポイントのテスト"""
    response = client.get("/api/smartcut/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "smartcut"}


def test_init_success():
    """POST /init の正常系テスト"""
    mock_scan_plugin = MagicMock()
    mock_scan_result = MagicMock()
    mock_scan_result.total_segments = 10
    mock_scan_result.highlight_candidates = [{"id": "h1"}]
    mock_scan_result.chapter_candidates = [{"id": "c1"}]
    mock_scan_result.estimated_cut_rate = 0.8
    mock_scan_plugin.execute.return_value.scan_result = mock_scan_result

    mock_smart_cut = MagicMock()
    mock_smart_cut.get_recommendation.return_value = {"recommended": "data"}

    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", return_value=mock_scan_plugin), \
         patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        
        payload = {
            "segments": [{"start": 0, "end": 10, "text": "hello"}],
            "opening_duration": 5.0,
            "ending_duration": 10.0
        }
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["scan_result"]["total_segments"] == 10
        assert data["scan_result"]["highlight_count"] == 1
        assert data["scan_result"]["chapter_count"] == 1
        assert data["scan_result"]["estimated_cut_rate"] == 0.8
        assert data["recommendation"] == {"recommended": "data"}


def test_init_import_error():
    """POST /init で ImportError が発生した時のテスト (500)"""
    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", side_effect=ImportError("Module not found")):
        payload = {"segments": []}
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 500
        assert "Failed to load required plugins" in response.json()["detail"]


def test_init_value_error():
    """POST /init で ValueError が発生した時のテスト (400)"""
    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", side_effect=ValueError("Invalid segments")):
        payload = {"segments": []}
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 400
        assert "Invalid segments" in response.json()["detail"]


def test_recommend_success():
    """POST /recommend の正常系テスト"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()  # 初期化済み
    mock_smart_cut.get_recommendation.return_value = {"rec": "ok"}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["recommendation"] == {"rec": "ok"}
        mock_smart_cut.update_recommendation.assert_called_with(30)


def test_recommend_not_initialized():
    """POST /recommend で未初期化の場合のテスト (400)"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None  # 未初期化

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_lock_success():
    """POST /lock の正常系テスト"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.lock_segment.return_value = True
    mock_smart_cut.get_locked_segments.return_value = [{"segment_id": "seg1"}]
    mock_smart_cut.get_recommendation.return_value = {"rec": "ok"}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        payload = {
            "segment_id": "seg1",
            "title": "title1",
            "start_time": 10.0,
            "end_time": 20.0,
            "reason": "must include"
        }
        response = client.post("/api/smartcut/lock", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["locked_segments"] == [{"segment_id": "seg1"}]
        assert data["recommendation"] == {"rec": "ok"}


def test_lock_validation_error():
    """POST /lock で start_time >= end_time のバリデーションエラーテスト"""
    payload = {
        "segment_id": "seg1",
        "title": "title1",
        "start_time": 20.0,
        "end_time": 10.0,  # 終了が開始より前
        "reason": "error"
    }
    response = client.post("/api/smartcut/lock", json=payload)
    assert response.status_code == 422  # FastAPI validation error


def test_unlock_success():
    """POST /unlock の正常系テスト"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.unlock_segment.return_value = True
    mock_smart_cut.get_locked_segments.return_value = []
    mock_smart_cut.get_recommendation.return_value = {"rec": "ok"}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/unlock", json={"segment_id": "seg1"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["locked_segments"] == []


def test_all_candidates_success():
    """GET /all-candidates の正常系テスト"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.get_all_candidates.return_value = {"highlights": []}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["candidates"] == {"highlights": []}


def test_finalize_success():
    """POST /finalize の正常系テスト"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.finalize.return_value = {"final": "ok"}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["finalized"] == {"final": "ok"}


# ------------------------------------------------------------
# Thumbnail API Tests
# ------------------------------------------------------------

def test_thumbnail_resolution_validation():
    """POST /thumbnail の最小解像度バリデーションエラーテスト"""
    payload = {
        "session_id": "sess_1",
        "task_id": "task_1",
        "width": 1000,  # 1280未満
        "height": 720,
        "text": "test"
    }
    response = client.post("/api/smartcut/thumbnail", json=payload)
    assert response.status_code == 422


def test_thumbnail_aspect_ratio_validation():
    """POST /thumbnail の16:9アスペクト比バリデーションエラーテスト"""
    payload = {
        "session_id": "sess_1",
        "task_id": "task_1",
        "width": 1280,
        "height": 800,  # 16:10
        "text": "test"
    }
    response = client.post("/api/smartcut/thumbnail", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_thumbnail_generation_success():
    """POST /thumbnail の正常系非同期タスク完了テスト"""
    mock_service = MagicMock()
    mock_agent = MagicMock()
    
    # get_task_status の遷移
    call_count = 0
    def get_status_side_effect(task_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "READY"
        elif call_count == 2:
            return "RUNNING"
        else:
            return "COMPLETED"
            
    mock_agent.get_task_status = AsyncMock(side_effect=get_status_side_effect)
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json.dumps({"image_path": "test.png"}),)
    mock_conn.execute.return_value = mock_cursor
    
    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
         
        payload = {
            "session_id": "sess_1",
            "task_id": "task_ok",
            "width": 1280,
            "height": 720,
            "text": "Success test"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "COMPLETED"
        assert data["thumbnail"]["image_path"] == "test.png"


@pytest.mark.asyncio
async def test_thumbnail_generation_failed():
    """POST /thumbnail のタスク失敗時のエラー詳細返却テスト (500)"""
    mock_service = MagicMock()
    mock_agent = MagicMock()
    
    mock_agent.get_task_status = AsyncMock(return_value="FAILED")
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json.dumps({"error": "Overlay generation timeout"}),)
    mock_conn.execute.return_value = mock_cursor
    
    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
         
        payload = {
            "session_id": "sess_1",
            "task_id": "task_fail",
            "width": 1280,
            "height": 720,
            "text": "Fail test"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert "Thumbnail task failed: Overlay generation timeout" in data["detail"]


@pytest.mark.asyncio
async def test_thumbnail_completed_no_result():
    """POST /thumbnail のタスク完了したがDB結果が空の時のテスト (500)"""
    mock_service = MagicMock()
    mock_agent = MagicMock()
    
    mock_agent.get_task_status = AsyncMock(return_value="COMPLETED")
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (None,) # 結果がNone
    mock_conn.execute.return_value = mock_cursor
    
    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock):
         
        payload = {
            "session_id": "sess_1",
            "task_id": "task_no_result",
            "width": 1280,
            "height": 720,
            "text": "No result test"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert "Thumbnail task completed but no result found" in data["detail"]


@pytest.mark.asyncio
async def test_thumbnail_db_error_on_result():
    """POST /thumbnail の結果取得時にSQLiteエラーが発生した時のテスト (500)"""
    mock_service = MagicMock()
    mock_agent = MagicMock()
    
    mock_agent.get_task_status = AsyncMock(return_value="COMPLETED")
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.Error("Mock DB connection failure")
    
    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock):
         
        payload = {
            "session_id": "sess_1",
            "task_id": "task_db_err",
            "width": 1280,
            "height": 720,
            "text": "DB error test"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert "Database error" in data["detail"]


@pytest.mark.asyncio
async def test_safe_sqlite_query_close_error_handling():
    """_safe_sqlite_query で conn.close() が失敗しても元の sqlite3.Error が伝播されるテスト"""
    from routers.smartcut import _safe_sqlite_query
    
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.Error("Original execute error")
    mock_conn.close.side_effect = Exception("Close connection error")
    
    with patch("sqlite3.connect", return_value=mock_conn):
        with pytest.raises(sqlite3.Error) as exc_info:
            await _safe_sqlite_query("dummy_path", "SELECT 1")
        assert "Original execute error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_safe_sqlite_query_retry_on_operational_error():
    """_safe_sqlite_query が OperationalError 時にリトライするテスト"""
    from routers.smartcut import _safe_sqlite_query
    
    mock_conn = MagicMock()
    # 2回 OperationalError を投げて、3回目で成功する
    mock_conn.execute.side_effect = [
        sqlite3.OperationalError("Database is locked"),
        sqlite3.OperationalError("Database is locked"),
        MagicMock()  # success
    ]
    
    with patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
         
        res = await _safe_sqlite_query("dummy_path", "UPDATE tasks SET status = 1")
        assert res is True
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.1)
        mock_sleep.assert_any_call(0.2)

