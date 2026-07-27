import sys
import os

# 重複インポートと ValueError を防ぐため、sys.path を backend ディレクトリのみに制限し、親ディレクトリを除去
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_dir)
def _norm(p):
    return os.path.normcase(os.path.abspath(p))

sys.path = [p for p in sys.path if _norm(p) not in (_norm(backend_dir), _norm(project_root))]
sys.path.insert(0, backend_dir)

import pydantic.root_model
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routers.approval_router import router, ApprovalRequest, DecisionRequest
from branding.history_manager import EventType

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_process_approval_approved():
    """Approved（承認）された場合のエンドポイント検証"""
    with patch("branding.history_manager.history_manager.log_event") as mock_log:
        response = client.post(
            "/api/approval",
            json={
                "approved": True,
                "feedback": "",
                "timestamp": "2026-05-24T12:00:00Z",
                "session_id": "session-123"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        mock_log.assert_called_once_with(
            EventType.USER_INTERACTION,
            {
                "type": "DASHBOARD_APPROVAL",
                "approved": True,
                "session_id": "session-123",
                "timestamp": "2026-05-24T12:00:00Z"
            }
        )


def test_process_approval_rejected():
    """Rejected（却下）された場合のエンドポイント検証"""
    with patch("branding.history_manager.history_manager.log_event") as mock_log:
        response = client.post(
            "/api/approval",
            json={
                "approved": False,
                "feedback": "Needs color correction",
                "timestamp": "2026-05-24T12:00:00Z",
                "session_id": "session-123"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert response.json()["feedback"] == "Needs color correction"
        mock_log.assert_called_once_with(
            EventType.USER_INTERACTION,
            {
                "type": "DASHBOARD_REJECTION",
                "approved": False,
                "session_id": "session-123",
                "feedback": "Needs color correction",
                "timestamp": "2026-05-24T12:00:00Z"
            }
        )


def test_process_approval_exception():
    """例外が発生した際のエラーハンドリング検証 (500)"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=RuntimeError("Database error")):
        response = client.post(
            "/api/approval",
            json={
                "approved": True,
                "feedback": "",
                "timestamp": "2026-05-24T12:00:00Z",
                "session_id": "session-123"
            }
        )
        assert response.status_code == 500
        assert "Database error" in response.json()["detail"]


def test_record_decision_success():
    """判定記録エンドポイントの正常系検証"""
    with patch("branding.history_manager.history_manager.log_event") as mock_log:
        response = client.post(
            "/api/approval/decision",
            json={
                "session_id": "session-456",
                "decision": "approved",
                "feedback": "Great work"
            }
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recorded"
        assert response.json()["decision"] == "approved"
        mock_log.assert_called_once_with(
            EventType.USER_INTERACTION,
            {
                "type": "DECISION",
                "session_id": "session-456",
                "decision": "approved",
                "feedback": "Great work"
            }
        )


def test_record_decision_exception():
    """例外が発生した際のエラーハンドリング検証 (500)"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=RuntimeError("Log failed")):
        response = client.post(
            "/api/approval/decision",
            json={
                "session_id": "session-456",
                "decision": "approved",
                "feedback": "Great work"
            }
        )
        assert response.status_code == 500
        assert "Log failed" in response.json()["detail"]


def test_get_approval_history_success():
    """履歴取得エンドポイントの正常系検証"""
    mock_events = [
        {"type": "DECISION", "session_id": "s1", "decision": "approved"}
    ]
    with patch("branding.history_manager.history_manager.get_recent_events", return_value=mock_events) as mock_get:
        response = client.get("/api/approval/history?limit=5")
        assert response.status_code == 200
        assert response.json()["history"] == mock_events
        mock_get.assert_called_once_with(
            event_type=EventType.USER_INTERACTION,
            limit=5
        )


def test_get_approval_history_exception():
    """履歴取得中の例外ハンドリング検証"""
    with patch("branding.history_manager.history_manager.get_recent_events", side_effect=RuntimeError("Fetch error")):
        response = client.get("/api/approval/history")
        assert response.status_code == 500
        assert "Fetch error" in response.json()["detail"]


def test_process_approval_http_exception():
    """process_approval で HTTPException が発生した場合の検証"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=HTTPException(status_code=400, detail="Bad Request")):
        response = client.post(
            "/api/approval",
            json={
                "approved": True,
                "feedback": "",
                "timestamp": "2026-05-24T12:00:00Z",
                "session_id": "session-123"
            }
        )
        assert response.status_code == 400
        assert "Bad Request" in response.json()["detail"]


def test_record_decision_http_exception():
    """record_decision で HTTPException が発生した場合の検証"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=HTTPException(status_code=400, detail="Bad Request")):
        response = client.post(
            "/api/approval/decision",
            json={
                "session_id": "session-456",
                "decision": "approved",
                "feedback": "Great work"
            }
        )
        assert response.status_code == 400
        assert "Bad Request" in response.json()["detail"]


def test_get_approval_history_http_exception():
    """get_approval_history で HTTPException が発生した場合の検証"""
    with patch("branding.history_manager.history_manager.get_recent_events", side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.get("/api/approval/history")
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]


def test_approval_request_model_validation():
    """ApprovalRequestモデルのバリデーションとデフォルト値の検証"""
    req = ApprovalRequest(approved=True)
    assert req.approved is True
    assert req.feedback == ""
    assert req.timestamp == ""
    assert req.session_id == ""


def test_decision_request_model_validation():
    """DecisionRequestモデルのバリデーションとデフォルト値の検証"""
    req = DecisionRequest(session_id="session-999", decision="approved")
    assert req.session_id == "session-999"
    assert req.decision == "approved"
    assert req.feedback == ""


def test_get_approval_history_default_limit():
    """limitパラメータを指定しない場合のデフォルト値（10）の検証"""
    mock_events = []
    with patch("branding.history_manager.history_manager.get_recent_events", return_value=mock_events) as mock_get:
        response = client.get("/api/approval/history")
        assert response.status_code == 200
        assert response.json()["history"] == mock_events
        mock_get.assert_called_once_with(
            event_type=EventType.USER_INTERACTION,
            limit=10
        )


def test_get_approval_history_invalid_limit():
    """limitパラメータに不正な型（文字列）を指定した場合のバリデーション検証 (422)"""
    response = client.get("/api/approval/history?limit=not-an-integer")
    assert response.status_code == 422
    # Pydantic v2 のエラーメッセージ形式に対応
    assert "type_error.integer" in response.text or "int_parsing" in response.text or "parsing" in response.text


def test_approval_request_invalid_types():
    """ApprovalRequestに不正なデータ型を送信した場合のバリデーション検証 (422)"""
    response = client.post(
        "/api/approval",
        json={
            "approved": {"not_a_bool": True},
            "session_id": "session-123"
        }
    )
    assert response.status_code == 422


def test_decision_request_missing_required():
    """DecisionRequestで必須フィールド(session_id)が欠落している場合の検証 (422)"""
    response = client.post(
        "/api/approval/decision",
        json={
            "decision": "approved",
            "feedback": "Great work"
        }
    )
    assert response.status_code == 422


# routers/approval_router.py 用の追加テストコード (エッジケース検証)
def test_approval_request_none_values():
    """ApprovalRequestのオプショナルフィールドにNoneを設定した場合のバリデーション検証 (422)"""
    response = client.post(
        "/api/approval",
        json={
            "approved": True,
            "feedback": None,
            "timestamp": "2026-05-24T12:00:00Z",
            "session_id": "session-123"
        }
    )
    assert response.status_code == 422


def test_decision_request_none_values():
    """DecisionRequestのフィールドにNoneを設定した場合のバリデーション検証 (422)"""
    response = client.post(
        "/api/approval/decision",
        json={
            "session_id": None,
            "decision": "approved",
            "feedback": "Great work"
        }
    )
    assert response.status_code == 422


def test_get_approval_history_negative_limit():
    """get_approval_historyでlimitに負の値を指定した場合の挙動検証 (422)"""
    response = client.get("/api/approval/history?limit=-5")
    assert response.status_code == 422


def test_process_approval_missing_session_id():
    """session_id が空または空白のみの場合に 400 を返すことを検証"""
    # 空文字列の場合
    response = client.post(
        "/api/approval",
        json={
            "approved": True,
            "feedback": "",
            "timestamp": "2026-05-24T12:00:00Z",
            "session_id": ""
        }
    )
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]

    # 空白のみの場合
    response = client.post(
        "/api/approval",
        json={
            "approved": True,
            "feedback": "",
            "timestamp": "2026-05-24T12:00:00Z",
            "session_id": "   "
        }
    )
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]


def test_record_decision_missing_session_id():
    """decisionの記録時にsession_idが空または空白のみの場合に 400 を返すことを検証"""
    response = client.post(
        "/api/approval/decision",
        json={
            "session_id": "",
            "decision": "approved",
            "feedback": "Great work"
        }
    )
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]


def test_record_decision_invalid_decision():
    """無効なdecisionが指定された場合に 400 を返すことを検証"""
    response = client.post(
        "/api/approval/decision",
        json={
            "session_id": "session-999",
            "decision": "invalid_value",
            "feedback": "Great work"
        }
    )
    assert response.status_code == 400
    assert "Invalid decision" in response.json()["detail"]

def test_process_approval_value_error():
    """process_approval で ValueError が発生した場合に 400 を返すことを検証"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=ValueError("Invalid event data format")):
        response = client.post(
            "/api/approval",
            json={
                "approved": True,
                "feedback": "",
                "timestamp": "2026-05-24T12:00:00Z",
                "session_id": "session-123"
            }
        )
        assert response.status_code == 400
        assert "Invalid event data format" in response.json()["detail"]


def test_record_decision_value_error():
    """record_decision で ValueError が発生した場合に 400 を返すことを検証"""
    with patch("branding.history_manager.history_manager.log_event", side_effect=ValueError("Invalid decision data")):
        response = client.post(
            "/api/approval/decision",
            json={
                "session_id": "session-456",
                "decision": "approved",
                "feedback": "Great work"
            }
        )
        assert response.status_code == 400
        assert "Invalid decision data" in response.json()["detail"]


def test_get_approval_history_value_error():
    """get_approval_history で ValueError が発生した場合に 400 を返すことを検証"""
    with patch("branding.history_manager.history_manager.get_recent_events", side_effect=ValueError("Invalid history limit parameter")):
        response = client.get("/api/approval/history?limit=10")
        assert response.status_code == 400
        assert "Invalid history limit parameter" in response.json()["detail"]


def test_get_approval_history_boundary_values():
    """limitパラメータの境界値検証"""
    mock_events = []
    with patch("branding.history_manager.history_manager.get_recent_events", return_value=mock_events) as mock_get:
        # limit=1 (下限境界値)
        response = client.get("/api/approval/history?limit=1")
        assert response.status_code == 200
        mock_get.assert_called_with(event_type=EventType.USER_INTERACTION, limit=1)

        # limit=100 (上限境界値)
        response = client.get("/api/approval/history?limit=100")
        assert response.status_code == 200
        mock_get.assert_called_with(event_type=EventType.USER_INTERACTION, limit=100)

    # limit=0 (下限未満)
    response = client.get("/api/approval/history?limit=0")
    assert response.status_code == 422

    # limit=101 (上限超)
    response = client.get("/api/approval/history?limit=101")
    assert response.status_code == 422


def test_process_approval_diverse_exceptions():
    """process_approval で多様な例外が発生した場合のエラーハンドリング検証 (500)"""
    exceptions_to_test = [
        KeyError("Key not found"),
        AttributeError("Attribute mismatch"),
        OSError("Disk failure")
    ]
    for exc in exceptions_to_test:
        with patch("branding.history_manager.history_manager.log_event", side_effect=exc):
            response = client.post(
                "/api/approval",
                json={
                    "approved": True,
                    "feedback": "",
                    "timestamp": "2026-05-24T12:00:00Z",
                    "session_id": "session-123"
                }
            )
            assert response.status_code == 500
            assert str(exc) in response.json()["detail"]


def test_record_decision_diverse_exceptions():
    """record_decision で多様な例外が発生した場合のエラーハンドリング検証 (500)"""
    exceptions_to_test = [
        KeyError("Key not found"),
        AttributeError("Attribute mismatch"),
        OSError("Disk failure")
    ]
    for exc in exceptions_to_test:
        with patch("branding.history_manager.history_manager.log_event", side_effect=exc):
            response = client.post(
                "/api/approval/decision",
                json={
                    "session_id": "session-456",
                    "decision": "approved",
                    "feedback": "Great work"
                }
            )
            assert response.status_code == 500
            assert str(exc) in response.json()["detail"]


def test_get_approval_history_diverse_exceptions():
    """get_approval_history で多様な例外が発生した場合のエラーハンドリング検証 (500)"""
    exceptions_to_test = [
        KeyError("Key not found"),
        AttributeError("Attribute mismatch"),
        OSError("Disk failure")
    ]
    for exc in exceptions_to_test:
        with patch("branding.history_manager.history_manager.get_recent_events", side_effect=exc):
            response = client.get("/api/approval/history")
            assert response.status_code == 500
            assert str(exc) in response.json()["detail"]
