import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from backend.routers.legacy_council_router import router
from agents.resolution_tracker import ResolutionStatus, Resolution

# FastAPI テストアプリの設定
app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def mock_resolution_tracker():
    with patch("agents.resolution_tracker.resolution_tracker") as mock:
        yield mock

@pytest.fixture
def mock_branding_manager():
    with patch("backend.routers.legacy_council_router.branding_manager") as mock:
        yield mock

def test_list_resolutions_no_status(mock_resolution_tracker):
    """GET /api/council/resolutions (statusなし)"""
    mock_resolution_tracker.list_resolutions.return_value = []
    
    response = client.get("/api/council/resolutions")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "resolutions": []}
    mock_resolution_tracker.list_resolutions.assert_called_once_with(status=None)

def test_list_resolutions_with_valid_status(mock_resolution_tracker):
    """GET /api/council/resolutions (有効なstatus)"""
    mock_resolution_tracker.list_resolutions.return_value = []
    
    response = client.get("/api/council/resolutions?status=draft")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "resolutions": []}
    mock_resolution_tracker.list_resolutions.assert_called_once_with(status=ResolutionStatus.DRAFT)

def test_list_resolutions_with_invalid_status(mock_resolution_tracker):
    """GET /api/council/resolutions (無効なstatus)"""
    response = client.get("/api/council/resolutions?status=invalid_status")
    assert response.status_code == 400

def test_list_resolutions_server_error(mock_resolution_tracker):
    """GET /api/council/resolutions (内部エラー)"""
    mock_resolution_tracker.list_resolutions.side_effect = RuntimeError("DB error")
    
    response = client.get("/api/council/resolutions")
    assert response.status_code == 500
    assert "DB error" in response.json()["detail"]

def test_vote_resolution_success(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (正常系)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/vote",
        json={"agent_name": "agent1", "vote": "APPROVE"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    mock_resolution_tracker.record_vote.assert_called_once_with(res_id, "agent1", "APPROVE")

def test_vote_resolution_not_found(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (存在しないID)"""
    res_id = "non-existent"
    mock_resolution_tracker.get_resolution.return_value = None
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/vote",
        json={"agent_name": "agent1", "vote": "APPROVE"}
    )
    assert response.status_code == 404

def test_vote_resolution_invalid_json(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (不正なJSON形式)"""
    response = client.post(
        "/api/council/resolutions/test-res-123/vote",
        content="invalid-json"
    )
    assert response.status_code == 400

def test_vote_resolution_missing_fields(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (必須フィールド欠損)"""
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    
    # agent_name欠損
    response = client.post(
        "/api/council/resolutions/test-res-123/vote",
        json={"vote": "APPROVE"}
    )
    assert response.status_code == 400
    
    # vote欠損
    response = client.post(
        "/api/council/resolutions/test-res-123/vote",
        json={"agent_name": "agent1"}
    )
    assert response.status_code == 400

def test_vote_resolution_invalid_fields(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (不正な値/非辞書型)"""
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    
    # voteの値が不正
    response = client.post(
        "/api/council/resolutions/test-res-123/vote",
        json={"agent_name": "agent1", "vote": "INVALID"}
    )
    assert response.status_code == 400
    
    # 非辞書型
    response = client.post(
        "/api/council/resolutions/test-res-123/vote",
        json=["not", "a", "dict"]
    )
    assert response.status_code == 400

def test_vote_resolution_server_error(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (内部エラー)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    mock_resolution_tracker.record_vote.side_effect = RuntimeError("DB write error")
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/vote",
        json={"agent_name": "agent1", "vote": "APPROVE"}
    )
    assert response.status_code == 500
    assert "DB write error" in response.json()["detail"]

def test_apply_gavel_approve(mock_resolution_tracker, mock_branding_manager):
    """POST /api/council/resolutions/{id}/gavel (正常系: APPROVE)"""
    res_id = "test-res-123"
    mock_res = MagicMock()
    mock_res.title = "New Rules"
    mock_res.proposed_changes = {"key": "value"}
    
    mock_resolution_tracker.get_resolution.return_value = mock_res
    mock_resolution_tracker.apply_gavel.return_value = True
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "APPROVE"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "decision": "APPROVE"}
    
    mock_resolution_tracker.apply_gavel.assert_called_once_with(res_id, "APPROVE")
    mock_branding_manager.evolve_constitution.assert_called_once_with({
        "type": "council_resolution",
        "resolution_id": res_id,
        "value": "New Rules",
        "changes": {"key": "value"}
    })

def test_apply_gavel_reject(mock_resolution_tracker, mock_branding_manager):
    """POST /api/council/resolutions/{id}/gavel (正常系: REJECT)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    mock_resolution_tracker.apply_gavel.return_value = True
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "REJECT"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "decision": "REJECT"}
    
    mock_resolution_tracker.apply_gavel.assert_called_once_with(res_id, "REJECT")
    mock_branding_manager.evolve_constitution.assert_not_called()

def test_apply_gavel_not_found(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (存在しないID)"""
    res_id = "non-existent"
    mock_resolution_tracker.get_resolution.return_value = None
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "APPROVE"}
    )
    assert response.status_code == 404

def test_apply_gavel_invalid_json(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (不正なJSON形式)"""
    response = client.post(
        "/api/council/resolutions/test-res-123/gavel",
        content="invalid-json"
    )
    assert response.status_code == 400

def test_apply_gavel_missing_fields(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (必須フィールド欠損)"""
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    
    response = client.post(
        "/api/council/resolutions/test-res-123/gavel",
        json={}
    )
    assert response.status_code == 400

def test_apply_gavel_invalid_fields(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (不正な値/非辞書型)"""
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    
    # decisionの値が不正
    response = client.post(
        "/api/council/resolutions/test-res-123/gavel",
        json={"decision": "INVALID"}
    )
    assert response.status_code == 400
    
    # 非辞書型
    response = client.post(
        "/api/council/resolutions/test-res-123/gavel",
        json=["not", "a", "dict"]
    )
    assert response.status_code == 400

def test_apply_gavel_server_error(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (内部エラー)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    mock_resolution_tracker.apply_gavel.side_effect = RuntimeError("Gavel failed")
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "APPROVE"}
    )
    assert response.status_code == 500
    assert "Gavel failed" in response.json()["detail"]


def test_propose_thumbnail_success(mock_resolution_tracker):
    """POST /api/council/resolutions/thumbnail-proposal (正常系: 自動決済対象)"""
    mock_res = MagicMock()
    mock_res.id = "thumbnail-res-123"
    mock_res.status = ResolutionStatus.VOTING
    mock_resolution_tracker.create_resolution.return_value = mock_res

    response = client.post(
        "/api/council/resolutions/thumbnail-proposal",
        json={
            "session_id": "session-abc",
            "thumbnail_path": "assets/thumb.png",
            "quality_score": 85.0,
            "standards_compliance": {"nhk": True, "youtuber": True}
        }
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["resolution_id"] == "thumbnail-res-123"
    assert res_data["auto_approve_eligible"] is True
    
    mock_resolution_tracker.create_resolution.assert_called_once()
    mock_resolution_tracker.update_status.assert_called_once_with("thumbnail-res-123", ResolutionStatus.VOTING)

def test_propose_thumbnail_not_eligible(mock_resolution_tracker):
    """POST /api/council/resolutions/thumbnail-proposal (正常系: 自動決済対象外 - スコア不足)"""
    mock_res = MagicMock()
    mock_res.id = "thumbnail-res-456"
    mock_res.status = ResolutionStatus.DRAFT
    mock_resolution_tracker.create_resolution.return_value = mock_res

    response = client.post(
        "/api/council/resolutions/thumbnail-proposal",
        json={
            "session_id": "session-abc",
            "thumbnail_path": "assets/thumb_poor.png",
            "quality_score": 75.0,
            "standards_compliance": {"nhk": True, "youtuber": True}
        }
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["auto_approve_eligible"] is False
    
    mock_resolution_tracker.create_resolution.assert_called_once()
    mock_resolution_tracker.update_status.assert_not_called()

def test_propose_thumbnail_invalid_data(mock_resolution_tracker):
    """POST /api/council/resolutions/thumbnail-proposal (異常系: 無効データ)"""
    # quality_score が範囲外
    response = client.post(
        "/api/council/resolutions/thumbnail-proposal",
        json={
            "session_id": "session-abc",
            "thumbnail_path": "assets/thumb.png",
            "quality_score": 120.0,
            "standards_compliance": {"nhk": True}
        }
    )
    assert response.status_code == 422 # Pydantic validation error

def test_apply_gavel_auto_approve_success(mock_resolution_tracker, mock_branding_manager):
    """POST /api/council/resolutions/{id}/gavel (正常系: AUTO決済成功)"""
    res_id = "test-res-auto"
    mock_res = MagicMock()
    mock_res.title = "High Quality Thumbnail"
    mock_res.proposed_changes = {
        "type": "thumbnail_proposal",
        "auto_approve": True
    }
    mock_resolution_tracker.get_resolution.return_value = mock_res
    mock_resolution_tracker.apply_gavel.return_value = True

    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "AUTO"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "decision": "APPROVE"}
    mock_resolution_tracker.apply_gavel.assert_called_once_with(res_id, "APPROVE")

def test_apply_gavel_auto_approve_not_eligible(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (異常系: 自動承認対象外の議案でAUTO決済要求)"""
    res_id = "test-res-manual"
    mock_res = MagicMock()
    mock_res.proposed_changes = {
        "type": "thumbnail_proposal",
        "auto_approve": False
    }
    mock_resolution_tracker.get_resolution.return_value = mock_res

    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "AUTO"}
    )
    assert response.status_code == 400
    assert "AUTO decision is only allowed" in response.json()["detail"]


def test_list_resolutions_value_error(mock_resolution_tracker):
    """GET /api/council/resolutions (ValueError時の内部エラー)"""
    mock_resolution_tracker.list_resolutions.side_effect = ValueError("Invalid list operation")
    
    response = client.get("/api/council/resolutions")
    assert response.status_code == 500
    assert "Invalid list operation" in response.json()["detail"]

def test_vote_resolution_key_error(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/vote (KeyError時の内部エラー)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    mock_resolution_tracker.record_vote.side_effect = KeyError("Resolution key missing")
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/vote",
        json={"agent_name": "agent1", "vote": "APPROVE"}
    )
    assert response.status_code == 500
    assert "Resolution key missing" in response.json()["detail"]

def test_apply_gavel_type_error(mock_resolution_tracker):
    """POST /api/council/resolutions/{id}/gavel (TypeError時の内部エラー)"""
    res_id = "test-res-123"
    mock_resolution_tracker.get_resolution.return_value = MagicMock()
    mock_resolution_tracker.apply_gavel.side_effect = TypeError("Gavel argument type mismatch")
    
    response = client.post(
        f"/api/council/resolutions/{res_id}/gavel",
        json={"decision": "APPROVE"}
    )
    assert response.status_code == 500
    assert "Gavel argument type mismatch" in response.json()["detail"]

def test_propose_thumbnail_runtime_error(mock_resolution_tracker):
    """POST /api/council/resolutions/thumbnail-proposal (RuntimeError時の内部エラー)"""
    mock_resolution_tracker.create_resolution.side_effect = RuntimeError("Failed to create proposal")

    response = client.post(
        "/api/council/resolutions/thumbnail-proposal",
        json={
            "session_id": "session-abc",
            "thumbnail_path": "assets/thumb.png",
            "quality_score": 85.0,
            "standards_compliance": {"nhk": True, "youtuber": True}
        }
    )
    assert response.status_code == 500
    assert "Failed to create proposal" in response.json()["detail"]
