"""
routers/quality.py の単体テスト
"""
import unittest
from unittest.mock import patch, MagicMock, mock_open
from fastapi.testclient import TestClient
from fastapi import FastAPI
import sys
from pathlib import Path

# backend ディレクトリを python パスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from backend.routers.quality import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestQualityRouter(unittest.TestCase):
    """Quality Router の全エンドポイントを検証するテストクラス"""

    @patch("quality_gate_agent.quality_gate.run_gate")
    def test_run_quality_check(self, mock_check):
        """POST /api/quality/check のテスト"""
        mock_check.return_value.to_dict.return_value = {"score": 95, "status": "pass"}
        payload = {
            "full_text": "テスト動画のスクリプトテキスト",
            "scenes": [{"id": "scene_1"}],
            "segments": [{"id": "segment_1"}]
        }
        response = client.post("/api/quality/check", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"score": 95, "status": "passed", "details": []})
        mock_check.assert_called_once_with({
            "full_text": "テスト動画のスクリプトテキスト",
            "scenes": [{"id": "scene_1"}],
            "segments": [{"id": "segment_1"}]
        })

    def test_get_quality_threshold(self):
        """GET /api/quality/threshold のテスト"""
        response = client.get("/api/quality/threshold")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "pass_threshold": 90,
                "block_threshold": 60,
                "warning_threshold": 70
            }
        )

    @patch("quality_gate_agent.quality_gate.run_gate")
    def test_verify_quality(self, mock_pre_check):
        """POST /api/quality/verify のテスト"""
        mock_pre_check.return_value.to_dict.return_value = {"valid": True}
        payload = {"render_id": "r123"}
        response = client.post("/api/quality/verify", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"valid": True, "status": "ok"})
        mock_pre_check.assert_called_once_with(payload)

    @patch("cleanup_manager.cleanup_manager.cleanup")
    @patch("cleanup_manager.cleanup_manager.preview_cleanup")
    def test_run_cleanup_dry_run(self, mock_preview, mock_run):
        """POST /api/quality/cleanup (dry_run=True) のテスト"""
        mock_preview.return_value = {"deleted": [], "dry_run": True}
        payload = {"category": "temp", "dry_run": True}
        response = client.post("/api/quality/cleanup", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": [], "dry_run": True})
        mock_preview.assert_called_once()
        mock_run.assert_not_called()

    @patch("cleanup_manager.cleanup_manager.cleanup")
    @patch("cleanup_manager.cleanup_manager.preview_cleanup")
    def test_run_cleanup_actual(self, mock_preview, mock_run):
        """POST /api/quality/cleanup (dry_run=False) のテスト"""
        mock_run.return_value = {"deleted_count": 5}
        payload = {"category": "temp", "dry_run": False}
        response = client.post("/api/quality/cleanup", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted_count": 5})
        mock_run.assert_called_once_with(category="temp")
        mock_preview.assert_not_called()

    @patch("cleanup_manager.cleanup_manager.preview_cleanup")
    def test_preview_cleanup(self, mock_preview):
        """GET /api/quality/cleanup/preview のテスト"""
        mock_preview.return_value = {"files": ["file1.tmp"]}
        response = client.get("/api/quality/cleanup/preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"files": ["file1.tmp"]})
        mock_preview.assert_called_once()

    @patch("cleanup_manager.cleanup_manager.get_storage_stats")
    def test_get_storage_stats(self, mock_stats):
        """GET /api/quality/storage/stats のテスト"""
        mock_stats.return_value = {"used_bytes": 1024}
        response = client.get("/api/quality/storage/stats")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"used_bytes": 1024})
        mock_stats.assert_called_once()

    @patch("ai_rhythm.semantic_split")
    def test_rhythm_split(self, mock_split):
        """POST /api/quality/rhythm/split のテスト"""
        mock_split.return_value = ["分割テキスト1", "分割テキスト2"]
        payload = {"text": "長いテロップ用の日本語テキスト", "target_chars": 10}
        response = client.post("/api/quality/rhythm/split", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"splits": ["分割テキスト1", "分割テキスト2"]})
        mock_split.assert_called_once_with("長いテロップ用の日本語テキスト", 10)

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_quick_decision(self, mock_mkdir, mock_file):
        """POST /api/quality/decision/quick のテスト"""
        payload = {
            "item_id": "item_001",
            "action": "approve",
            "timestamp": "2026-06-03T12:00:00",
            "comment": "OK"
        }
        response = client.post("/api/quality/decision/quick", json=payload)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data["status"], "ok")
        self.assertEqual(res_data["decision"]["item_id"], "item_001")
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

    def test_apply_suggestion(self):
        """POST /api/quality/apply-suggestion のテスト"""
        payload = {
            "suggestion": "フォントサイズを大きくする",
            "index": 1
        }
        response = client.post("/api/quality/apply-suggestion", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "applied", "index": 1})

    def test_undo_suggestion(self):
        """POST /api/quality/undo-suggestion のテスト"""
        payload = {
            "suggestion": "フォントサイズを大きくする",
            "index": 1
        }
        response = client.post("/api/quality/undo-suggestion", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "undone", "index": 1})

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_approve_review(self, mock_mkdir, mock_file):
        """POST /api/quality/review/approve のテスト"""
        payload = {
            "stages": [{"stage": 1, "completed": True}],
            "approved_at": "2026-06-03T12:00:00"
        }
        response = client.post("/api/quality/review/approve", json=payload)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data["status"], "approved")
        self.assertEqual(res_data["entry"]["total_stages"], 1)
        self.assertEqual(res_data["entry"]["completed_stages"], 1)
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

    @patch("cleanup_manager.cleanup_manager.cleanup")
    def test_run_cleanup_none_request(self, mock_run):
        """POST /api/quality/cleanup (payload=None) のテスト"""
        mock_run.return_value = {"deleted_count": 0}
        response = client.post("/api/quality/cleanup", json=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted_count": 0})
        mock_run.assert_called_once_with(category=None)

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_quick_decision_empty_timestamp(self, mock_mkdir, mock_file):
        """POST /api/quality/decision/quick (timestamp="") のテスト"""
        payload = {
            "item_id": "item_002",
            "action": "reject",
            "timestamp": "",
            "comment": "NG"
        }
        response = client.post("/api/quality/decision/quick", json=payload)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data["status"], "ok")
        self.assertTrue(len(res_data["decision"]["timestamp"]) > 0)
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_approve_review_empty_approved_at(self, mock_mkdir, mock_file):
        """POST /api/quality/review/approve (approved_at="") のテスト"""
        payload = {
            "stages": [{"stage": 1, "completed": False}],
            "approved_at": ""
        }
        response = client.post("/api/quality/review/approve", json=payload)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data["status"], "approved")
        self.assertTrue(len(res_data["entry"]["approved_at"]) > 0)
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()
