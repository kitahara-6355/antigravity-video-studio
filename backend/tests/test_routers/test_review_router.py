import pytest
import sys
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from routers.review_router import ReviewStage, router

# TestClient setup
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

# mock modules and classes
mock_progressive_review = MagicMock()

class MockProductionContext:
    def __init__(self, task_id):
        self.task_id = task_id
        self._extensions = {}
    def get_extension(self, key, default):
        return self._extensions.get(key, default)

# =====================================================================
# review_router.py Test Cases
# =====================================================================

def test_get_all_stages(client):
    """GET /api/review/stages の正常系"""
    response = client.get("/api/review/stages")
    assert response.status_code == 200
    data = response.json()
    assert "stages" in data
    assert data["total"] == 5
    assert len(data["stages"]) == 5

def test_get_stage_info_success(client):
    """GET /api/review/stages/{stage} の正常系"""
    for stage in ReviewStage:
        response = client.get(f"/api/review/stages/{stage.value}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == stage.value
        assert "name" in data

@pytest.mark.asyncio
async def test_get_stage_info_not_found():
    """get_stage_info で定義外のステージが指定された際の 404 HTTPException"""
    from routers.review_router import get_stage_info
    # 無効な引数を渡して、STAGE_INFO.get(stage) が None となり HTTPException が発生することを確認
    with pytest.raises(HTTPException) as exc_info:
        await get_stage_info("invalid_stage")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Stage not found"

def test_get_stage_report_success(client):
    """GET /api/review/stages/{stage}/report の正常系"""
    mock_progressive_review.generate_stage_report.return_value = "# Report Markdown Content"
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/stages/subtitle/report")
        assert response.status_code == 200
        data = response.json()
        assert data["stage"] == "subtitle"
        assert data["report_markdown"] == "# Report Markdown Content"
        assert data["status"] == "generated"

def test_get_stage_report_http_exception(client):
    """GET /api/review/stages/{stage}/report の HTTPException re-raise 挙動"""
    mock_progressive_review.generate_stage_report.side_effect = HTTPException(status_code=403, detail="Forbidden Stage")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/stages/subtitle/report")
        assert response.status_code == 403
        assert response.json()["detail"] == "Forbidden Stage"

def test_get_stage_report_general_exception(client):
    """GET /api/review/stages/{stage}/report の一般例外発生時(500)の挙動"""
    mock_progressive_review.generate_stage_report.side_effect = ValueError("Database connection failure")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/stages/subtitle/report")
        assert response.status_code == 500
        assert "Database connection failure" in response.json()["detail"]

def test_approve_stage_success(client):
    """POST /api/review/stages/{stage}/approve の承認成功パス"""
    mock_progressive_review.approve_stage.return_value = True
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post("/api/review/stages/subtitle/approve")
        assert response.status_code == 200
        data = response.json()
        assert data["approved"] is True
        assert "承認しました" in data["message"]

def test_approve_stage_failed(client):
    """POST /api/review/stages/{stage}/approve の承認失敗(400)パス"""
    mock_progressive_review.approve_stage.return_value = False
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post("/api/review/stages/subtitle/approve")
        assert response.status_code == 400
        assert response.json()["detail"] == "Approval failed"

def test_approve_stage_http_exception(client):
    """POST /api/review/stages/{stage}/approve の HTTPException re-raise 挙動"""
    mock_progressive_review.approve_stage.side_effect = HTTPException(status_code=402, detail="Payment required")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post("/api/review/stages/subtitle/approve")
        assert response.status_code == 402
        assert response.json()["detail"] == "Payment required"

def test_approve_stage_general_exception(client):
    """POST /api/review/stages/{stage}/approve の一般例外発生時(500)の挙動"""
    mock_progressive_review.approve_stage.side_effect = RuntimeError("Approve operation failed")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post("/api/review/stages/subtitle/approve")
        assert response.status_code == 500
        assert "Approve operation failed" in response.json()["detail"]

def test_request_revision_success(client):
    """POST /api/review/stages/{stage}/revision の修正要求成功パス"""
    mock_progressive_review.request_revision.return_value = True
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post(
            "/api/review/stages/subtitle/revision",
            json={"stage": "subtitle", "notes": "Style correction needed", "items": ["sub-1"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["revision_requested"] is True
        assert data["notes"] == "Style correction needed"
        assert "修正を受け付けました" in data["message"]

def test_request_revision_failed(client):
    """POST /api/review/stages/{stage}/revision の修正要求失敗(400)パス"""
    mock_progressive_review.request_revision.return_value = False
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post(
            "/api/review/stages/subtitle/revision",
            json={"stage": "subtitle", "notes": "Fix style"}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Revision request failed"

def test_request_revision_http_exception(client):
    """POST /api/review/stages/{stage}/revision の HTTPException re-raise 挙動"""
    mock_progressive_review.request_revision.side_effect = HTTPException(status_code=409, detail="Conflict revision request")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post(
            "/api/review/stages/subtitle/revision",
            json={"stage": "subtitle", "notes": "Conflict notes"}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "Conflict revision request"

def test_request_revision_general_exception(client):
    """POST /api/review/stages/{stage}/revision の一般例外発生時(500)の挙動"""
    mock_progressive_review.request_revision.side_effect = Exception("General write error")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review,
            ReviewStage=ReviewStage
        )
    }):
        response = client.post(
            "/api/review/stages/subtitle/revision",
            json={"stage": "subtitle", "notes": "Style correction"}
        )
        assert response.status_code == 500
        assert "General write error" in response.json()["detail"]

def test_get_review_status_success(client):
    """GET /api/review/status の正常系"""
    mock_progressive_review.get_pending_stages.return_value = [ReviewStage.SUBTITLE, ReviewStage.TELOP]
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        )
    }):
        response = client.get("/api/review/status")
        assert response.status_code == 200
        data = response.json()
        assert "subtitle" in data["pending_stages"]
        assert "telop" in data["pending_stages"]
        assert data["pending_count"] == 2
        assert data["all_approved"] is False
        assert data["stages"]["subtitle"]["pending"] is True
        assert data["stages"]["video"]["pending"] is False

def test_get_review_status_http_exception(client):
    """GET /api/review/status の HTTPException re-raise 挙動"""
    mock_progressive_review.get_pending_stages.side_effect = HTTPException(status_code=401, detail="Unauthorized request")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        )
    }):
        response = client.get("/api/review/status")
        assert response.status_code == 401
        assert response.json()["detail"] == "Unauthorized request"

def test_get_review_status_general_exception(client):
    """GET /api/review/status の一般例外発生時(500)の挙動"""
    mock_progressive_review.get_pending_stages.side_effect = Exception("System status error")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        )
    }):
        response = client.get("/api/review/status")
        assert response.status_code == 500
        assert "System status error" in response.json()["detail"]

def test_get_review_summary_success(client):
    """GET /api/review/summary の正常系"""
    mock_context_instance = MagicMock()
    mock_context_instance.get_extension.return_value = {
        "pending_revisions": 0,
        "completed": True
    }
    mock_progressive_review.execute.return_value = mock_context_instance
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["completed"] is True
        assert data["ready_for_render"] is True

def test_get_review_summary_http_exception(client):
    """GET /api/review/summary の HTTPException re-raise 挙動"""
    mock_progressive_review.execute.side_effect = HTTPException(status_code=400, detail="Invalid context")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/summary")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid context"

def test_get_review_summary_general_exception(client):
    """GET /api/review/summary の一般例外発生時(500)の挙動"""
    mock_progressive_review.execute.side_effect = Exception("Summary generation failed")
    
    with patch.dict("sys.modules", {
        "plugins.progressive_review_plugin": MagicMock(
            progressive_review=mock_progressive_review
        ),
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        response = client.get("/api/review/summary")
        assert response.status_code == 500
        assert "Summary generation failed" in response.json()["detail"]


def test_get_context_direct():
    """_get_context ヘルパー関数を直接呼び出すテストケース"""
    from routers.review_router import _get_context
    
    with patch.dict("sys.modules", {
        "core": MagicMock(
            ProductionContext=MockProductionContext
        )
    }):
        context = _get_context("test_direct_task_id")
        assert context.task_id == "test_direct_task_id"

