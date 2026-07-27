import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
import json
from pathlib import Path
import sys
import os

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "routers"))

from fastapi import FastAPI
import collaboration
from collaboration import FeedbackRequest, JournalRequest, DecisionRequest
app = FastAPI()
app.include_router(collaboration.router)
client = TestClient(app)

def test_process_feedback():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.register_feedback.return_value = {"status": "success"}
        
        payload = {
            "suggestion_id": "test-sugg-123",
            "action": "approve",
            "role": "owner",
            "comment": "Nice thumbnail suggestions"
        }
        response = client.post("/api/feedback", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        mock_bm.register_feedback.assert_called_once_with(
            suggestion_id="test-sugg-123",
            action="approve",
            role="owner",
            comment="Nice thumbnail suggestions"
        )

def test_get_journal():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.get_journal.return_value = [{"author": "admin", "content": "hello"}]
        
        response = client.get("/api/journal")
        
        assert response.status_code == 200
        assert response.json() == [{"author": "admin", "content": "hello"}]
        mock_bm.get_journal.assert_called_once()

def test_add_journal_entry():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.add_journal_entry.return_value = {"status": "added"}
        
        payload = {
            "author": "owner",
            "content": "Updated thumbnail criteria"
        }
        response = client.post("/api/journal", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "added"}
        mock_bm.add_journal_entry.assert_called_once_with("owner", "Updated thumbnail criteria")

def test_record_decision():
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.record_decision.return_value = "decision-999"
        
        payload = {
            "target_type": "thumbnail",
            "target_path": "drafts/thumb_1.jpg",
            "target_description": "First thumbnail draft",
            "decision": "approve",
            "reason": "Bright colors",
            "scene_info": {"scene": 1},
            "mood_settings": {"mood": "happy"},
            "tags": ["test"]
        }
        response = client.post("/api/decision/record", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "recorded", "decision_id": "decision-999"}
        mock_dl.record_decision.assert_called_once_with(
            target_type="thumbnail",
            target_path="drafts/thumb_1.jpg",
            target_description="First thumbnail draft",
            decision="approve",
            reason="Bright colors",
            scene_info={"scene": 1},
            mood_settings={"mood": "happy"},
            tags=["test"]
        )

def test_get_decision_context():
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.get_ai_context.return_value = "AI Context Summary"
        
        response = client.get("/api/decision/context?target_type=thumbnail")
        
        assert response.status_code == 200
        assert response.json() == "AI Context Summary"
        mock_dl.get_ai_context.assert_called_once_with("thumbnail")

def test_get_decision_stats():
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.get_stats.return_value = {"total": 10}
        
        response = client.get("/api/decision/stats")
        
        assert response.status_code == 200
        assert response.json() == {"total": 10}
        mock_dl.get_stats.assert_called_once()

def test_sync_decisions():
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.sync_to_evolution_log.return_value = {"status": "synced"}
        
        response = client.post("/api/decision/sync")
        
        assert response.status_code == 200
        assert response.json() == {"status": "synced"}
        mock_dl.sync_to_evolution_log.assert_called_once()

def test_get_director_profile():
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.get_director_preferences.return_value = {"preferences": []}
        
        response = client.get("/api/director-profile")
        
        assert response.status_code == 200
        assert response.json() == {"preferences": []}
        mock_dl.get_director_preferences.assert_called_once()

@pytest.mark.asyncio
async def test_trigger_council_session():
    with patch("agents.council_graph.run_council", new_callable=AsyncMock) as mock_rc:
        mock_rc.return_value = {"session_result": "ok"}
        
        response = client.post("/api/council/session", json={})
        
        assert response.status_code == 200
        assert response.json() == {"session_result": "ok"}
        mock_rc.assert_called_once_with(
            user_query="現在のチャンネル成長についての戦略的分析をお願いします。",
            council_mode="post_production"
        )

def test_council_decision_approve():
    with patch("branding_manager.branding_manager") as mock_bm:
        payload = {
            "outcome": "APPROVE",
            "session_id": "session-111"
        }
        response = client.post("/api/council/decision", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {
            "status": "processed",
            "outcome": "APPROVE",
            "session_id": "session-111"
        }
        mock_bm.apply_xp.assert_called_once_with(50)

def test_council_decision_other():
    with patch("branding_manager.branding_manager") as mock_bm:
        payload = {
            "outcome": "REJECT",
            "session_id": "session-222"
        }
        response = client.post("/api/council/decision", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {
            "status": "processed",
            "outcome": "REJECT",
            "session_id": "session-222"
        }
        mock_bm.apply_xp.assert_not_called()

def test_list_philosophies_exists():
    mock_data = {"philosophies": ["P1", "P2"]}
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
        
        response = client.get("/api/philosophies")
        
        assert response.status_code == 200
        assert response.json() == {"philosophies": ["P1", "P2"]}

def test_list_philosophies_not_exists():
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get("/api/philosophies")
        
        assert response.status_code == 200
        assert response.json() == {"philosophies": []}

def test_list_resolutions():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.get_resolutions.return_value = ["Res1", "Res2"]
        
        response = client.get("/api/resolutions?status=active")
        
        assert response.status_code == 200
        assert response.json() == {"resolutions": ["Res1", "Res2"]}
        mock_bm.get_resolutions.assert_called_once_with("active")

def test_vote_resolution():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.record_vote.return_value = {"status": "voted"}
        
        payload = {"vote": "yes"}
        response = client.post("/api/resolutions/res-123/vote", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "voted"}
        mock_bm.record_vote.assert_called_once_with("res-123", payload)

def test_apply_gavel():
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.apply_gavel.return_value = {"status": "passed"}
        
        payload = {"action": "approve"}
        response = client.post("/api/resolutions/res-123/gavel", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "passed"}
        mock_bm.apply_gavel.assert_called_once_with("res-123", payload)



# === Edge cases & validation tests added for robustness ===

def test_process_feedback_validation_error():
    """Feedback request missing required fields returns 422"""
    payload = {
        "suggestion_id": "test-sugg-123",
        # missing action, role
    }
    response = client.post("/api/feedback", json=payload)
    assert response.status_code == 422


def test_add_journal_entry_validation_error():
    """Journal request missing author returns 422"""
    payload = {
        "content": "Updated thumbnail criteria"
        # missing author
    }
    response = client.post("/api/journal", json=payload)
    assert response.status_code == 422


def test_record_decision_optional_fields_missing():
    """Decision record works when optional fields are missing or None"""
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.record_decision.return_value = "decision-1000"
        
        payload = {
            "target_type": "thumbnail",
            "target_path": "drafts/thumb_1.jpg",
            "target_description": "First thumbnail draft",
            "decision": "approve",
            "reason": "Bright colors"
            # optional fields: scene_info, mood_settings, tags are omitted
        }
        response = client.post("/api/decision/record", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "recorded", "decision_id": "decision-1000"}
        mock_dl.record_decision.assert_called_once_with(
            target_type="thumbnail",
            target_path="drafts/thumb_1.jpg",
            target_description="First thumbnail draft",
            decision="approve",
            reason="Bright colors",
            scene_info=None,
            mood_settings=None,
            tags=None
        )


def test_record_decision_validation_error():
    """Decision record fails with 422 when required fields are missing"""
    payload = {
        "target_type": "thumbnail"
        # missing target_path, target_description, decision, reason
    }
    response = client.post("/api/decision/record", json=payload)
    assert response.status_code == 422


def test_get_decision_context_no_params():
    """Getting decision context without query params passes None to decision_logger"""
    with patch("decision_logger.decision_logger") as mock_dl:
        mock_dl.get_ai_context.return_value = "Default AI Context"
        
        response = client.get("/api/decision/context")
        
        assert response.status_code == 200
        assert response.json() == "Default AI Context"
        mock_dl.get_ai_context.assert_called_once_with(None)


def test_trigger_council_session_defaults():
    """Council session triggers with default values when body is empty"""
    with patch("agents.council_graph.run_council", new_callable=AsyncMock) as mock_rc:
        mock_rc.return_value = {"session_result": "default_ok"}
        
        response = client.post("/api/council/session", json={})
        
        assert response.status_code == 200
        assert response.json() == {"session_result": "default_ok"}
        mock_rc.assert_called_once_with(
            user_query="現在のチャンネル成長についての戦略的分析をお願いします。",
            council_mode="post_production"
        )


def test_council_decision_missing_fields():
    """Council decision uses default values if fields are missing in payload"""
    with patch("branding_manager.branding_manager") as mock_bm:
        # missing outcome, session_id
        response = client.post("/api/council/decision", json={})
        
        assert response.status_code == 200
        assert response.json() == {
            "status": "processed",
            "outcome": "UNKNOWN",
            "session_id": ""
        }
        mock_bm.apply_xp.assert_not_called()


def test_list_philosophies_invalid_json():
    """If evolution_log.json is invalid json, empty philosophies list is returned safely"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    with patch("pathlib.Path.exists", return_value=True),          patch("builtins.open", mock_open(read_data="invalid json")):
        
        response = client_no_raise.get("/api/philosophies")
        assert response.status_code == 200
        assert response.json() == {"philosophies": []}


def test_vote_resolution_invalid_json():
    """Sending invalid JSON to vote endpoint yields 400 error"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    response = client_no_raise.post(
        "/api/resolutions/res-123/vote",
        content="not a json",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


def test_apply_gavel_invalid_json():
    """Sending invalid JSON to gavel endpoint yields 400 error"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    response = client_no_raise.post(
        "/api/resolutions/res-123/gavel",
        content="not a json",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


def test_trigger_council_session_with_json_body():
    """Council session triggers with json body parameters"""
    with patch("agents.council_graph.run_council", new_callable=AsyncMock) as mock_rc:
        mock_rc.return_value = {"session_result": "body_ok"}
        
        payload = {
            "query": "ボディによるクエリ",
            "council_mode": "body_mode"
        }
        response = client.post("/api/council/session", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"session_result": "body_ok"}
        mock_rc.assert_called_once_with(
            user_query="ボディによるクエリ",
            council_mode="body_mode"
        )


def test_trigger_council_session_with_params():
    """Council session triggers with explicit query parameters"""
    with patch("agents.council_graph.run_council", new_callable=AsyncMock) as mock_rc:
        mock_rc.return_value = {"session_result": "custom_ok"}
        
        response = client.post("/api/council/session?query=テストクエリ&council_mode=custom_mode")
        
        assert response.status_code == 200
        assert response.json() == {"session_result": "custom_ok"}
        mock_rc.assert_called_once_with(
            user_query="テストクエリ",
            council_mode="custom_mode"
        )


def test_list_philosophies_os_error():
    """If opening evolution_log.json raises OSError, a 500 error is returned when exceptions are not raised"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", side_effect=OSError("Permission denied")):
        
        response = client_no_raise.get("/api/philosophies")
        assert response.status_code == 500



def test_list_resolutions_no_status():
    """Getting resolutions without status query parameter passes None to branding_manager"""
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.get_resolutions.return_value = ["Res1", "Res2"]
        
        response = client.get("/api/resolutions")
        
        assert response.status_code == 200
        assert response.json() == {"resolutions": ["Res1", "Res2"]}
        mock_bm.get_resolutions.assert_called_once_with(None)


def test_list_philosophies_missing_key():
    """If evolution_log.json exists but lacks the 'philosophies' key, return empty list"""
    mock_data = {"other_key": "val"}
    with patch("pathlib.Path.exists", return_value=True),          patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
        
        response = client.get("/api/philosophies")
        
        assert response.status_code == 200
        assert response.json() == {"philosophies": []}


def test_process_feedback_comment_omitted():
    """Feedback request works when comment field is omitted (defaults to empty string)"""
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.register_feedback.return_value = {"status": "success"}
        
        payload = {
            "suggestion_id": "test-sugg-123",
            "action": "approve",
            "role": "owner"
            # comment is omitted
        }
        response = client.post("/api/feedback", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        mock_bm.register_feedback.assert_called_once_with(
            suggestion_id="test-sugg-123",
            action="approve",
            role="owner",
            comment=""
        )


def test_process_feedback_japanese_and_emojis():
    """Japanese and emojis in feedback comment are handled correctly"""
    with patch("branding_manager.branding_manager") as mock_bm:
        mock_bm.register_feedback.return_value = {"status": "success"}
        
        payload = {
            "suggestion_id": "test-sugg-123",
            "action": "approve",
            "role": "owner",
            "comment": "素晴らしいサムネイルですね！ 👍✨"
        }
        response = client.post("/api/feedback", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "success"}
        mock_bm.register_feedback.assert_called_once_with(
            suggestion_id="test-sugg-123",
            action="approve",
            role="owner",
            comment="素晴らしいサムネイルですね！ 👍✨"
        )


def test_list_philosophies_decode_error():
    """If evolution_log.json throws UnicodeDecodeError, a 500 error is returned when exceptions are not raised"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    with patch("pathlib.Path.exists", return_value=True), \
         patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte")):
        
        response = client_no_raise.get("/api/philosophies")
        assert response.status_code == 500


def test_vote_resolution_runtime_error():
    """If request.json() raises a RuntimeError, a 500 error is returned when exceptions are not raised"""
    client_no_raise = TestClient(app, raise_server_exceptions=False)
    with patch("fastapi.Request.json", side_effect=RuntimeError("Connection closed")):
        response = client_no_raise.post(
            "/api/resolutions/res-123/vote",
            json={"vote": "yes"}
        )
        assert response.status_code == 500


# =====================================================================
# 11. 実結合テスト（モックなしで decision_logger と FastAPI をテスト）
# =====================================================================

def test_router_integration_with_real_logger(tmp_path):
    """
    decision_logger.decision_logger の実体を使って、
    APIエンドポイント経由での記録・取得・プロファイル生成が
    Attributeエラーや型エラーなく正常に動作することを検証する
    """
    from decision_logger import DecisionLogger
    import collaboration
    
    # テスト用のクリーンなロガーインスタンスを設定
    test_log_dir = tmp_path / "branding"
    test_log_file = test_log_dir / "decision_log.json"
    
    real_logger = DecisionLogger()
    real_logger.log_dir = test_log_dir
    real_logger.log_file = test_log_file
    real_logger.decisions = []
    
    # ルーター側の _get_decision_logger 呼び出しがこの real_logger を返すようにパッチ
    with patch("collaboration._get_decision_logger", return_value=real_logger):
        # 1. 記録テスト (/api/decision/record)
        payload = {
            "target_type": "screenshot",
            "target_path": "test_shot.png",
            "target_description": "実テスト画像",
            "decision": "reject",
            "reason": "こだわり却下理由",
            "tags": ["tempo", "color"]
        }
        response = client.post("/api/decision/record", json=payload)
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "recorded"
        decision_id = res_data["decision_id"]
        assert decision_id is not None
        
        # 実際にデータが記録されたか
        assert len(real_logger.decisions) == 1
        assert real_logger.decisions[0].decision_id == decision_id
        assert real_logger.decisions[0].decision == "reject"
        
        # 2. AI向けコンテキスト取得テスト (/api/decision/context)
        response_ctx = client.get("/api/decision/context?target_type=screenshot")
        assert response_ctx.status_code == 200
        context_text = response_ctx.json()
        assert "ユーザーの過去の意思決定" in context_text
        assert "実テスト画像" in context_text
        assert "こだわり却下理由" in context_text
        
        # 3. 監督プロファイル取得テスト (/api/director-profile)
        response_prof = client.get("/api/director-profile")
        assert response_prof.status_code == 200
        profile_data = response_prof.json()
        assert "こだわり（却下傾向）" in profile_data
        assert profile_data["こだわり（却下傾向）"] == {"tempo": 1, "color": 1}
        assert "承認率" in profile_data
