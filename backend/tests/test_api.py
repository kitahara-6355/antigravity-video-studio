"""
API テスト

推奨タスク R5.1: バックエンドAPIテスト
主要APIエンドポイントのテスト
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import sys
import os
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path



# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# main.pyからappをインポート（テスト時）
# from main import app


class TestDashboardAPI:
    """ダッシュボードAPIテスト"""
    
    def test_get_status(self, client):
        """ステータス取得"""
        response = client.get("/api/dashboard/status")
        assert response.status_code == 200
        data = response.json()
        assert "phase" in data
        assert "progress" in data
    
    def test_start_processing(self, client):
        """処理開始"""
        response = client.post("/api/dashboard/process/start")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
    
    def test_health_check(self, client):
        """ヘルスチェック"""
        response = client.get("/api/dashboard/health")
        assert response.status_code == 200


class TestApprovalAPI:
    """承認APIテスト"""
    
    def test_approve(self, client):
        """承認処理"""
        response = client.post("/api/approval", json={
            "approved": True,
            "feedback": "",
            "timestamp": "2026-01-11T12:00:00",
            "session_id": "test-session-123"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
    
    def test_reject_with_feedback(self, client):
        """却下処理（フィードバック付き）"""
        response = client.post("/api/approval", json={
            "approved": False,
            "feedback": "もっとエモくしてください",
            "timestamp": "2026-01-11T12:00:00",
            "session_id": "test-session-123"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["feedback"] == "もっとエモくしてください"


class TestPhilosophyAPI:
    """哲学APIテスト"""
    
    def test_list_philosophies(self, client):
        """哲学一覧取得"""
        response = client.get("/api/philosophy/list")
        assert response.status_code == 200
        data = response.json()
        assert "philosophies" in data
    
    def test_add_philosophy(self, client):
        """哲学追加"""
        response = client.post("/api/philosophy/add", json={
            "content": "視聴者の心を動かす編集を目指す",
            "source": "test"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "added"
    
    def test_get_summary(self, client):
        """サマリー取得"""
        response = client.get("/api/philosophy/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_count" in data


class TestErrorHandling:
    """エラーハンドリングテスト"""
    
    def test_invalid_endpoint(self, client):
        """存在しないエンドポイント"""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
    
    def test_invalid_json(self, client):
        """不正なJSON"""
        response = client.post(
            "/api/approval",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]


# Pytest fixture
@pytest.fixture
def client():
    """テストクライアントフィクスチャ"""
    from main import app
    return TestClient(app)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestLegacyManagementAPI:
    """レガシーマネジメントルーターの非同期/パフォーマンス改善テスト"""

    def test_read_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Constitution Active" in response.json()["status"]

    def test_legacy_process_start(self, client):
        """プロセス非同期開始の検証"""
        response = client.post("/api/process/start")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"

    def test_legacy_video_upload(self, client, tmp_path):
        """動画アップロード時の非同期I/Oとリソース解放の検証"""
        dummy_video = tmp_path / "test_upload.mp4"
        dummy_video.write_bytes(b"dummy video content")
        
        with open(dummy_video, "rb") as f:
            response = client.post(
                "/api/settings/video",
                files={"file": ("test_upload.mp4", f, "video/mp4")}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        
        temp_path = "temp_test_upload.mp4"
        assert not os.path.exists(temp_path)

    def test_legacy_collaboration_feedback(self, client):
        """コラボレーションフィードバックの非同期処理検証"""
        from unittest.mock import patch
        from branding_manager import branding_manager
        if "profiles" not in branding_manager.user_model:
            branding_manager.user_model["profiles"] = {
                "admin": {"ranks": {"tech_rank": {"level": "Novice", "xp": 0}}},
                "owner": {"ranks": {"biz_rank": {"level": "Novice", "xp": 0}}}
            }
        
        payload = {
            "suggestion_id": "sug-123",
            "action": "approve",
            "role": "admin",
            "comment": "Good job"
        }
        with patch("branding_manager.branding_manager.log_evolution", return_value={"summary": "Success"}):
            response = client.post("/api/collaboration/feedback", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_legacy_collaboration_journal(self, client):
        """ジャーナルノートの非同期記録検証"""
        from unittest.mock import patch
        payload = {
            "author": "admin",
            "content": "Optimized legacy endpoints for performance"
        }
        with patch("branding_manager.branding_manager.log_evolution", return_value={"summary": "Success"}):
            response = client.post("/api/collaboration/journal", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "success"


class TestAntigravityAPI:
    """Antigravity 3.0 API テスト"""

    def test_get_proper_nouns(self, client):
        with patch("antigravity_api.proper_noun_dict.get_all_entries", return_value=[{"id": "1", "incorrect": "A", "correct": "B"}]):
            response = client.get("/api/antigravity/proper-nouns")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["entries"][0]["incorrect"] == "A"

    def test_add_proper_noun_success(self, client):
        with patch("antigravity_api.proper_noun_dict.add_entry", return_value={"id": "2"}) as mock_add:
            response = client.post("/api/antigravity/proper-nouns", json={"incorrect": "A", "correct": "B"})
            assert response.status_code == 200
            assert response.json()["success"] is True
            mock_add.assert_called_once()

    def test_add_proper_noun_fail(self, client):
        with patch("antigravity_api.proper_noun_dict.add_entry", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/proper-nouns", json={"incorrect": "A", "correct": "B"})
            assert response.status_code == 400

    def test_process_srt_success(self, client, tmp_path):
        from unittest.mock import mock_open
        dummy_srt = tmp_path / "test.srt"
        dummy_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello", encoding="utf-8")
        
        with patch("antigravity_api.AntigravityPipeline.process_srt", return_value={"status": "completed"}) as mock_process, \
             patch("pathlib.Path.unlink") as mock_unlink:
            
            with open(dummy_srt, "rb") as f:
                response = client.post(
                    "/api/antigravity/process-srt",
                    files={"file": ("test.srt", f, "text/plain")}
                )
            assert response.status_code == 200
            assert response.json()["status"] == "completed"

    def test_process_srt_fail(self, client, tmp_path):
        dummy_srt = tmp_path / "test.srt"
        dummy_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello", encoding="utf-8")
        
        with patch("antigravity_api.AntigravityPipeline.process_srt", side_effect=ValueError("Process error")):
            with open(dummy_srt, "rb") as f:
                response = client.post(
                    "/api/antigravity/process-srt",
                    files={"file": ("test.srt", f, "text/plain")}
                )
            assert response.status_code == 500

    def test_get_telop_proposals(self, client, tmp_path):
        from unittest.mock import mock_open
        with patch("antigravity_api.Path.exists", return_value=True), \
             patch("antigravity_api.Path.glob", return_value=[Path("test_proposals.json")]), \
             patch("builtins.open", mock_open(read_data='{"telop_candidates": [], "scene_proposals": []}')):
             
            response = client.get("/api/antigravity/telop-proposals")
            assert response.status_code == 200
            assert "proposals" in response.json()

    def test_approve_telop(self, client):
        with patch("antigravity_api.record_approval") as mock_approve:
            response = client.post("/api/antigravity/telop-proposals/1/approve", json={"action": "approve", "permanent": True})
            assert response.status_code == 200
            assert response.json()["action"] == "approved"
            mock_approve.assert_called_once_with({"proposal_id": "1", "type": "telop"}, tags=["telop"], permanent=True)

    def test_reject_telop(self, client):
        with patch("antigravity_api.record_rejection") as mock_reject:
            response = client.post("/api/antigravity/telop-proposals/1/approve", json={"action": "reject"})
            assert response.status_code == 200
            assert response.json()["action"] == "rejected"
            mock_reject.assert_called_once_with({"proposal_id": "1", "type": "telop"}, reason="rejected", tags=["telop"])

    def test_approve_telop_real_loop_check(self, client):
        """record_approvalをモックせず内部のlearning_loop.record_decisionをモックして型チェック検証"""
        with patch("antigravity_api.learning_loop.record_decision") as mock_record_decision:
            response = client.post("/api/antigravity/telop-proposals/1/approve", json={"action": "approve", "permanent": True})
            assert response.status_code == 200
            mock_record_decision.assert_called_once()
            called_args = mock_record_decision.call_args[1]
            assert called_args["content"] == {"proposal_id": "1", "type": "telop"}
            assert "telop" in called_args["tags"]

    def test_reject_telop_real_loop_check(self, client):
        """record_rejectionをモックせず内部のlearning_loop.record_decisionをモックして型チェック検証"""
        with patch("antigravity_api.learning_loop.record_decision") as mock_record_decision:
            response = client.post("/api/antigravity/telop-proposals/1/approve", json={"action": "reject"})
            assert response.status_code == 200
            mock_record_decision.assert_called_once()
            called_args = mock_record_decision.call_args[1]
            assert called_args["content"] == {"proposal_id": "1", "type": "telop"}
            assert called_args["reason"] == "rejected"
            assert "telop" in called_args["tags"]

    def test_get_assets(self, client):
        with patch("antigravity_api.asset_library.assets", []):
            response = client.get("/api/antigravity/assets")
            assert response.status_code == 200
            assert "assets" in response.json()

    def test_scan_assets(self, client):
        with patch("antigravity_api.asset_library.assets", []):
            response = client.post("/api/antigravity/assets/scan")
            assert response.status_code == 200
            assert response.json()["success"] is True

    def test_get_asset_sufficiency(self, client):
        with patch("antigravity_api.asset_library.get_sufficiency_report", return_value={"score": 100}):
            response = client.get("/api/antigravity/assets/sufficiency")
            assert response.status_code == 200
            assert response.json()["score"] == 100

    def test_generate_thumbnail_success(self, client):
        with patch("antigravity_api.generate_thumbnail", return_value={"url": "img.png"}):
            response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test"})
            assert response.status_code == 200
            assert response.json()["url"] == "img.png"

    def test_generate_thumbnail_fail(self, client):
        with patch("antigravity_api.generate_thumbnail", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test"})
            assert response.status_code == 500

    def test_generate_opening_success(self, client):
        with patch("antigravity_api.generate_opening", return_value={"url": "opening.mp4"}):
            response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美麗"})
            assert response.status_code == 200
            assert response.json()["url"] == "opening.mp4"

    def test_generate_opening_fail(self, client):
        with patch("antigravity_api.generate_opening", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美麗"})
            assert response.status_code == 500

    def test_generate_ending_success(self, client):
        with patch("antigravity_api.generate_ending", return_value={"url": "ending.mp4"}):
            response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美麗"})
            assert response.status_code == 200
            assert response.json()["url"] == "ending.mp4"

    def test_generate_ending_fail(self, client):
        with patch("antigravity_api.generate_ending", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美麗"})
            assert response.status_code == 500

    def test_get_self_review_status(self, client):
        response = client.get("/api/antigravity/self-review/status")
        assert response.status_code == 200
        assert "thresholds" in response.json()

    def test_run_self_review_success(self, client):
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.score.overall = 90
        mock_result.issues = []
        with patch("antigravity_api.self_review_engine.review", return_value=mock_result):
            response = client.post("/api/antigravity/self-review/check", json={"content": "test", "type": "text"})
            assert response.status_code == 200
            assert response.json()["passed"] is True

    def test_run_self_review_fail(self, client):
        with patch("antigravity_api.self_review_engine.review", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/self-review/check", json={"content": "test", "type": "text"})
            assert response.status_code == 500

    def test_get_pending_proposals(self, client):
        with patch("antigravity_api.learning_loop.get_pending_proposals", return_value=[]):
            response = client.get("/api/antigravity/learning/pending")
            assert response.status_code == 200
            assert "proposals" in response.json()

    def test_approve_learning(self, client):
        with patch("antigravity_api.record_approval") as mock_approve:
            response = client.post("/api/antigravity/learning/approve", json={"proposal_id": "1", "action": "approve", "permanent": True})
            assert response.status_code == 200
            mock_approve.assert_called_once_with({"proposal_id": "1", "type": "learning"}, permanent=True)

    def test_reject_learning(self, client):
        with patch("antigravity_api.record_rejection") as mock_reject:
            response = client.post("/api/antigravity/learning/approve", json={"proposal_id": "1", "action": "reject"})
            assert response.status_code == 200
            mock_reject.assert_called_once_with({"proposal_id": "1", "type": "learning"})

    def test_get_preferences(self, client):
        with patch("antigravity_api.learning_loop.get_preferences", return_value={}):
            response = client.get("/api/antigravity/learning/preferences")
            assert response.status_code == 200

    def test_get_editor_status(self, client):
        with patch("antigravity_api.check_ffmpeg", return_value=True):
            response = client.get("/api/antigravity/editor/status")
            assert response.status_code == 200
            assert response.json()["ffmpeg_available"] is True

    def test_create_final_video_success(self, client):
        with patch("antigravity_api.video_editor.create_final_video", return_value={"output": "final.mp4"}):
            response = client.post("/api/antigravity/editor/create-final", json={"main_video": "main.mp4"})
            assert response.status_code == 200
            assert response.json()["output"] == "final.mp4"

    def test_create_final_video_fail(self, client):
        with patch("antigravity_api.video_editor.create_final_video", side_effect=ValueError("Failed")):
            response = client.post("/api/antigravity/editor/create-final", json={"main_video": "main.mp4"})
            assert response.status_code == 500

    def test_get_pipeline_status_endpoint(self, client):
        with patch("antigravity_api.check_ffmpeg", return_value=True), \
             patch("antigravity_api.AntigravityPipeline.get_pipeline_status", return_value={
                 "proper_noun_entries": 1, "pending_confirmations": 0, "available_assets": 0, "pending_proposals": 0
             }):
            response = client.get("/api/antigravity/status")
            assert response.status_code == 200
            assert response.json()["proper_noun_entries"] == 1

    def test_add_proper_noun_http_exception(self, client):
        with patch("antigravity_api.proper_noun_dict.add_entry", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/proper-nouns", json={"incorrect": "test", "correct": "test"})
            assert response.status_code == 400

    def test_process_srt_http_exception(self, client, tmp_path):
        dummy_srt = tmp_path / "test.srt"
        dummy_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello", encoding="utf-8")
        with patch("antigravity_api.AntigravityPipeline.process_srt", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            with open(dummy_srt, "rb") as f:
                response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", f, "text/plain")})
            assert response.status_code == 400

    def test_generate_thumbnail_http_exception(self, client):
        with patch("antigravity_api.generate_thumbnail", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test"})
            assert response.status_code == 400

    def test_generate_opening_http_exception(self, client):
        with patch("antigravity_api.generate_opening", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美麗"})
            assert response.status_code == 400

    def test_generate_ending_http_exception(self, client):
        with patch("antigravity_api.generate_ending", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美麗"})
            assert response.status_code == 400

    def test_run_self_review_http_exception(self, client):
        with patch("antigravity_api.self_review_engine.review", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/self-review/check", json={"content": "test", "type": "text"})
            assert response.status_code == 400

    def test_create_final_video_http_exception(self, client):
        with patch("antigravity_api.video_editor.create_final_video", side_effect=HTTPException(status_code=400, detail="HTTP error")):
            response = client.post("/api/antigravity/editor/create-final", json={"main_video": "main.mp4"})
            assert response.status_code == 400

    def test_get_telop_proposals_not_exist(self, client):
        """提案ディレクトリが存在しない場合の挙動検証（C1分岐網羅）"""
        with patch("antigravity_api.Path.exists", return_value=False):
            response = client.get("/api/antigravity/telop-proposals")
            assert response.status_code == 200
            assert response.json() == {"proposals": []}

    def test_approve_telop_not_permanent(self, client):
        """恒久化しないテロップ承認の挙動検証（C1分岐網羅）"""
        with patch("antigravity_api.record_approval") as mock_approve:
            response = client.post("/api/antigravity/telop-proposals/1/approve", json={"action": "approve", "permanent": False})
            assert response.status_code == 200
            assert response.json()["action"] == "approved"
            assert response.json()["permanent"] is False
            mock_approve.assert_not_called()



