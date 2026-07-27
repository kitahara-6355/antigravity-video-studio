"""
routers/smartcut.py に対するカバレッジ100%ユニットテスト
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
from unittest.mock import MagicMock, patch, AsyncMock

# backend ディレクトリをパスに追加
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from routers.smartcut import router, _get_smart_cut
import routers.smartcut

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_global_instance():
    """テストごとにグローバルな _smart_cut_instance をリセット"""
    routers.smartcut._smart_cut_instance = None
    yield
    routers.smartcut._smart_cut_instance = None


def test_health_check():
    """GET /api/smartcut/health の正常系テスト"""
    response = client.get("/api/smartcut/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "smartcut"}


def test_get_smart_cut_lazy_load():
    """_get_smart_cut() の遅延ロードとシングルトン動作テスト"""
    mock_plugin_instance = MagicMock()
    with patch("plugins.smart_cut_plugin.SmartCutPlugin", return_value=mock_plugin_instance):
        inst1 = _get_smart_cut()
        inst2 = _get_smart_cut()
        assert inst1 is mock_plugin_instance
        assert inst2 is mock_plugin_instance


# ============================================================
# /init エンドポイントのテスト
# ============================================================

def test_init_smartcut_success():
    """POST /api/smartcut/init 正常系"""
    # LightweightScanPluginのモック
    mock_scan_plugin = MagicMock()
    # ProductionContextおよびscan_resultのモック
    mock_context = MagicMock()
    mock_scan_result = MagicMock()
    mock_scan_result.total_segments = 5
    mock_scan_result.highlight_candidates = [{"id": "h1"}]
    mock_scan_result.chapter_candidates = [{"id": "c1"}]
    mock_scan_result.estimated_cut_rate = 0.8
    mock_context.scan_result = mock_scan_result
    mock_scan_plugin.execute.return_value = mock_context

    # SmartCutPluginのモック
    mock_smart_cut = MagicMock()
    mock_smart_cut.get_recommendation.return_value = {"recommended_duration": 15}

    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", return_value=mock_scan_plugin), \
         patch("core.context.ProductionContext", return_value=mock_context), \
         patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):

        payload = {
            "segments": [{"start": 0.0, "end": 10.0}],
            "opening_duration": 12.0,
            "ending_duration": 22.0
        }
        response = client.post("/api/smartcut/init", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["scan_result"]["total_segments"] == 5
        assert data["scan_result"]["highlight_count"] == 1
        assert data["scan_result"]["estimated_cut_rate"] == 0.8
        assert data["recommendation"] == {"recommended_duration": 15}
        
        # _context がリセットされ、SmartCutContextが再設定されることを確認
        assert mock_smart_cut._context is not None
        mock_smart_cut.update_recommendation.assert_called_with(15)


def test_init_smartcut_http_exception():
    """POST /api/smartcut/init 異常系: HTTPExceptionが透過されること"""
    mock_scan_plugin = MagicMock()
    mock_scan_plugin.execute.side_effect = HTTPException(status_code=403, detail="Forbidden scan")

    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", return_value=mock_scan_plugin):
        payload = {
            "segments": [],
            "opening_duration": 10.0,
            "ending_duration": 20.0
        }
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 403
        assert response.json()["detail"] == "Forbidden scan"


def test_init_smartcut_general_exception():
    """POST /api/smartcut/init 異常系: 一般例外が500に変換されること"""
    mock_scan_plugin = MagicMock()
    mock_scan_plugin.execute.side_effect = RuntimeError("Scan failed unexpectedly")

    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", return_value=mock_scan_plugin):
        payload = {
            "segments": [],
            "opening_duration": 10.0,
            "ending_duration": 20.0
        }
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 500
        assert "Scan failed unexpectedly" in response.json()["detail"]


# ============================================================
# /recommend エンドポイントのテスト
# ============================================================

def test_recommend_success():
    """POST /api/smartcut/recommend 正常系"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()  # 初期化済み状態
    mock_smart_cut.get_recommendation.return_value = {"recommended_duration": 30}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["recommendation"] == {"recommended_duration": 30}
        mock_smart_cut.update_recommendation.assert_called_with(30)


def test_recommend_uninitialized():
    """POST /api/smartcut/recommend 異常系: 未初期化"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None  # 未初期化状態

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_recommend_http_exception():
    """POST /api/smartcut/recommend 異常系: HTTPExceptionが透過されること"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.update_recommendation.side_effect = HTTPException(status_code=402, detail="Payment Required")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 402
        assert response.json()["detail"] == "Payment Required"


def test_recommend_general_exception():
    """POST /api/smartcut/recommend 異常系: 一般例外"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.update_recommendation.side_effect = RuntimeError("Key error during recommendation")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 30})
        assert response.status_code == 500
        assert "Key error during recommendation" in response.json()["detail"]


# ============================================================
# /lock エンドポイントのテスト
# ============================================================

def test_lock_success():
    """POST /api/smartcut/lock 正常系"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.lock_segment.return_value = True
    mock_smart_cut.get_locked_segments.return_value = [{"segment_id": "seg_1"}]
    mock_smart_cut.get_recommendation.return_value = {"recommended_duration": 15}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        payload = {
            "segment_id": "seg_1",
            "title": "Locked Scene",
            "start_time": 10.0,
            "end_time": 20.0,
            "reason": "Must include this segment"
        }
        response = client.post("/api/smartcut/lock", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["locked_segments"] == [{"segment_id": "seg_1"}]
        assert data["recommendation"] == {"recommended_duration": 15}
        mock_smart_cut.lock_segment.assert_called_with(
            segment_id="seg_1",
            title="Locked Scene",
            start=10.0,
            end=20.0,
            reason="Must include this segment"
        )


def test_lock_uninitialized():
    """POST /api/smartcut/lock 異常系: 未初期化"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        payload = {
            "segment_id": "seg_1",
            "title": "Locked Scene",
            "start_time": 10.0,
            "end_time": 20.0,
        }
        response = client.post("/api/smartcut/lock", json=payload)
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_lock_validation_error():
    """POST /api/smartcut/lock 異常系: Pydanticによる開始/終了時間バリデーション"""
    payload = {
        "segment_id": "seg_1",
        "title": "Locked Scene",
        "start_time": 20.0,
        "end_time": 10.0,  # start_time >= end_time
    }
    response = client.post("/api/smartcut/lock", json=payload)
    assert response.status_code == 422
    assert "start_time must be less than end_time" in response.text


def test_lock_http_exception():
    """POST /api/smartcut/lock 異常系: HTTPExceptionが透過されること"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.lock_segment.side_effect = HTTPException(status_code=409, detail="Segment already locked")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        payload = {
            "segment_id": "seg_1",
            "title": "Locked Scene",
            "start_time": 10.0,
            "end_time": 20.0,
        }
        response = client.post("/api/smartcut/lock", json=payload)
        assert response.status_code == 409
        assert response.json()["detail"] == "Segment already locked"


def test_lock_general_exception():
    """POST /api/smartcut/lock 異常系: 一般例外"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.lock_segment.side_effect = RuntimeError("Database failure during lock")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        payload = {
            "segment_id": "seg_1",
            "title": "Locked Scene",
            "start_time": 10.0,
            "end_time": 20.0,
        }
        response = client.post("/api/smartcut/lock", json=payload)
        assert response.status_code == 500
        assert "Database failure during lock" in response.json()["detail"]


# ============================================================
# /unlock エンドポイントのテスト
# ============================================================

def test_unlock_success():
    """POST /api/smartcut/unlock 正常系"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.unlock_segment.return_value = True
    mock_smart_cut.get_locked_segments.return_value = []
    mock_smart_cut.get_recommendation.return_value = {}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/unlock", json={"segment_id": "seg_1"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_smart_cut.unlock_segment.assert_called_with("seg_1")


def test_unlock_uninitialized():
    """POST /api/smartcut/unlock 異常系: 未初期化"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/unlock", json={"segment_id": "seg_1"})
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_unlock_http_exception():
    """POST /api/smartcut/unlock 異常系: HTTPException"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.unlock_segment.side_effect = HTTPException(status_code=404, detail="Segment not found")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/unlock", json={"segment_id": "seg_1"})
        assert response.status_code == 404
        assert response.json()["detail"] == "Segment not found"


def test_unlock_general_exception():
    """POST /api/smartcut/unlock 異常系: 一般例外"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.unlock_segment.side_effect = AttributeError("Attribute error during unlock")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/unlock", json={"segment_id": "seg_1"})
        assert response.status_code == 500
        assert "Attribute error during unlock" in response.json()["detail"]


# ============================================================
# /all-candidates エンドポイントのテスト
# ============================================================

def test_all_candidates_success():
    """GET /api/smartcut/all-candidates 正常系"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.get_all_candidates.return_value = {"highlights": [], "chapters": []}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["candidates"] == {"highlights": [], "chapters": []}


def test_all_candidates_uninitialized():
    """GET /api/smartcut/all-candidates 異常系: 未初期化"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_all_candidates_http_exception():
    """GET /api/smartcut/all-candidates 異常系: HTTPException"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.get_all_candidates.side_effect = HTTPException(status_code=403, detail="Candidates access denied")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 403
        assert response.json()["detail"] == "Candidates access denied"


def test_all_candidates_general_exception():
    """GET /api/smartcut/all-candidates 異常系: 一般例外"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.get_all_candidates.side_effect = Exception("General candidate load failure")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.get("/api/smartcut/all-candidates")
        assert response.status_code == 500
        assert "General candidate load failure" in response.json()["detail"]


# ============================================================
# /finalize エンドポイントのテスト
# ============================================================

def test_finalize_success():
    """POST /api/smartcut/finalize 正常系"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.finalize.return_value = {"duration": 900.0, "segments_applied": 3}

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["finalized"] == {"duration": 900.0, "segments_applied": 3}


def test_finalize_uninitialized():
    """POST /api/smartcut/finalize 異常系: 未初期化"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = None

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 400
        assert "SmartCut not initialized" in response.json()["detail"]


def test_finalize_http_exception():
    """POST /api/smartcut/finalize 異常系: HTTPException"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.finalize.side_effect = HTTPException(status_code=409, detail="Finalize conflict")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 409
        assert response.json()["detail"] == "Finalize conflict"


def test_finalize_general_exception():
    """POST /api/smartcut/finalize 異常系: 一般例外"""
    mock_smart_cut = MagicMock()
    mock_smart_cut._context = MagicMock()
    mock_smart_cut.finalize.side_effect = Exception("General failure during finalize")

    with patch("routers.smartcut._get_smart_cut", return_value=mock_smart_cut):
        response = client.post("/api/smartcut/finalize")
        assert response.status_code == 500
        assert "General failure during finalize" in response.json()["detail"]


# ============================================================
# 堅牢性向上のための追加テスト（実プラグイン連携およびバリデーション）
# ============================================================

def test_recommend_non_preset_clipping_integration():
    """POST /api/smartcut/recommend 実プラグイン連携: 規定外の目標尺を指定した際に最も近いプリセット値にクリップされること"""
    from plugins.smart_cut_plugin import SmartCutPlugin, SmartCutContext
    
    real_smart_cut = SmartCutPlugin()
    real_smart_cut._context = SmartCutContext(
        all_highlights=[],
        all_chapters=[],
        opening_duration=10.0,
        ending_duration=20.0
    )
    
    # target_duration_minutes に規定外の 100 を指定した際、自動的に 60 にクリップされるはず
    with patch("routers.smartcut._get_smart_cut", return_value=real_smart_cut):
        response = client.post("/api/smartcut/recommend", json={"target_duration_minutes": 100})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["recommendation"]["target_duration_minutes"] == 60


def test_init_negative_duration_validation():
    """POST /api/smartcut/init 異常系: 負のオープニング/エンディング動画尺指定時のバリデーションエラー"""
    payload = {
        "segments": [],
        "opening_duration": -5.0,  # ge=0.0 違反
        "ending_duration": 10.0
    }
    response = client.post("/api/smartcut/init", json=payload)
    assert response.status_code == 422
    assert "opening_duration" in response.text


# ============================================================
# /thumbnail エンドポイントのテスト
# ============================================================

def test_thumbnail_success():
    """POST /api/smartcut/thumbnail 正常系: 1280x720 16:9 サムネイル生成成功"""
    mock_service = MagicMock()
    mock_agent = AsyncMock()
    mock_agent.get_task_status.side_effect = ["READY", "COMPLETED", "COMPLETED"]

    # sqlite3 のモック
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('{"thumbnail_path": "temp_thumbnails/thumb.jpg", "size": 1024}',)
    mock_conn.execute.return_value = mock_cursor

    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn):

        payload = {
            "session_id": "session_123",
            "task_id": "task_123",
            "width": 1280,
            "height": 720,
            "text": "Valid Session Thumbnail"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["status"] == "COMPLETED"
        assert data["thumbnail"]["thumbnail_path"] == "temp_thumbnails/thumb.jpg"


def test_thumbnail_validation_error():
    """POST /api/smartcut/thumbnail 異常系: 解像度不足およびアスペクト比不正によるバリデーションエラー"""
    # 解像度不足 (1280x720未満)
    payload_too_small = {
        "session_id": "session_123",
        "task_id": "task_123",
        "width": 1000,
        "height": 562,
        "text": "Too Small"
    }
    response = client.post("/api/smartcut/thumbnail", json=payload_too_small)
    assert response.status_code == 422
    assert "greater_than_equal" in response.text

    # アスペクト比不正 (16:9でない)
    payload_wrong_aspect = {
        "session_id": "session_123",
        "task_id": "task_123",
        "width": 1280,
        "height": 800,
        "text": "Wrong Aspect"
    }
    response = client.post("/api/smartcut/thumbnail", json=payload_wrong_aspect)
    assert response.status_code == 422
    assert "Aspect ratio must be 16:9" in response.text


def test_thumbnail_task_failed():
    """POST /api/smartcut/thumbnail 異常系: タスク実行失敗時の挙動"""
    mock_service = MagicMock()
    mock_agent = AsyncMock()
    mock_agent.get_task_status.side_effect = ["READY", "FAILED", "FAILED"]

    # sqlite3 のモック
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ('{"error": "Generation failed due to OOM"}',)
    mock_conn.execute.return_value = mock_cursor

    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn):

        payload = {
            "session_id": "session_123",
            "task_id": "task_fail_123",
            "width": 1280,
            "height": 720,
            "text": "Failed Thumbnail"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 500
        assert "Generation failed due to OOM" in response.json()["detail"]


def test_thumbnail_database_error():
    """POST /api/smartcut/thumbnail 異常系: SQLiteエラー発生時の挙動"""
    mock_service = MagicMock()
    mock_agent = AsyncMock()
    mock_agent.get_task_status.side_effect = ["READY", "COMPLETED", "COMPLETED"]

    import sqlite3
    # sqlite3.connect が例外を投げるようにモック
    with patch("services.smartcut_strategy_service.SmartCutStrategyService", return_value=mock_service), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", side_effect=sqlite3.Error("Locked database")):

        payload = {
            "session_id": "session_123",
            "task_id": "task_db_err_123",
            "width": 1280,
            "height": 720,
            "text": "Database Error Thumbnail"
        }
        response = client.post("/api/smartcut/thumbnail", json=payload)
        assert response.status_code == 500
        assert "Database error" in response.json()["detail"]




# ============================================================
# Phase 33 バグ修正に伴う追加検証テスト
# ============================================================

def test_init_smartcut_value_error_produces_400():
    """POST /api/smartcut/init 異常系: ValueError発生時に400エラーになることを保証するテスト"""
    mock_scan_plugin = MagicMock()
    mock_scan_plugin.execute.side_effect = ValueError("Database connection lost during scan")

    with patch("plugins.lightweight_scan_plugin.LightweightScanPlugin", return_value=mock_scan_plugin):
        payload = {
            "segments": [],
            "opening_duration": 10.0,
            "ending_duration": 20.0
        }
        response = client.post("/api/smartcut/init", json=payload)
        assert response.status_code == 400
        assert "Database connection lost during scan" in response.json()["detail"]
