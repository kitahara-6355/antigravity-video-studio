import sys
import os
# プロジェクトルート (backendディレクトリ) を sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
from unittest.mock import patch, MagicMock
import requests
import json
import subprocess
from pathlib import Path

# テスト対象のモジュール
import phase2_10run

# 正常系のモックデータ定義
MOCK_COMPLETED_DATA = {
    "status": "completed",
    "result": {
        "segments_count": 5,
        "preview_path": "/path/to/preview.mp4",
        "final_path": "/path/to/final.mp4",
        "quality_score": 92,
        "duration_seconds": 120,
        "stage_results": [
            {"name": "文字起こし", "success": True, "detail": "5 segments found"},
            {"name": "AI校閲", "success": True, "detail": "2 corrections applied"},
            {"name": "SmartCut", "success": True, "detail": "cut from 5m to 1m"},
        ],
        "quality_details": {
            "score": 92,
            "category_report": [
                {"category": "core"},
                {"category": "template"},
                {"category": "broadcast"},
                {"category": "youtube"},
            ]
        },
        "metadata": {
            "titles": ["驚くべき動画"],
            "tags": ["テスト", "自動化", "動画", "AI", "パイプライン"],
            "chapters": [{"time": "0:00", "title": "イントロ"}]
        }
    }
}


# ==========================================
# phase2_validator.py のテスト
# ==========================================

class TestPhase2Validator:

    def test_check_stage_result(self):
        from phase2_validator import check_stage_result
        stages = [
            {"name": "文字起こし", "success": True},
            {"name": "AI校閲", "success": False}
        ]
        res = check_stage_result(stages, "文字起こし")
        assert res == {"name": "文字起こし", "success": True}
        
        res = check_stage_result(stages, "SmartCut")
        assert res is None

        # リスト以外
        assert check_stage_result(None, "文字起こし") is None
        # dict以外
        assert check_stage_result([None], "文字起こし") is None

    def test_get_file_existence_and_size(self):
        from phase2_validator import _get_file_existence_and_size
        # 存在しないファイル
        exists, size = _get_file_existence_and_size("non_existent_file.mp4")
        assert exists is False
        assert size == 0

        # 不正な型
        exists, size = _get_file_existence_and_size(None)
        assert exists is False
        assert size == 0

    def test_check_transcribe(self):
        from phase2_validator import _check_transcribe
        stages = [{"name": "文字起こし", "success": True}]
        result = {"segments_count": 5}
        ok, detail = _check_transcribe(result, stages)
        assert ok is True
        assert "segments=5" in detail

        # segments_count が 0 の場合
        result = {"segments_count": 0}
        ok, detail = _check_transcribe(result, stages)
        assert ok is False

    def test_check_proofread(self):
        from phase2_validator import _check_proofread
        stages = [{"name": "AI校閲", "success": True, "detail": "applied"}]
        ok, detail = _check_proofread(stages)
        assert ok is True
        assert detail == "applied"

    def test_check_smartcut(self):
        from phase2_validator import _check_smartcut
        stages = [{"name": "SmartCut", "success": True, "detail": "cutok"}]
        ok, detail = _check_smartcut(stages)
        assert ok is True
        assert detail == "cutok"

    def test_check_quality_gate(self):
        from phase2_validator import _check_quality_gate
        quality_details = {
            "score": 85,
            "category_report": [
                {"category": "core"},
                {"category": "template"},
                {"category": "broadcast"},
                {"category": "youtube"},
            ]
        }
        ok, detail = _check_quality_gate(quality_details)
        assert ok is True
        assert "score=85" in detail

        # スコアが低い場合
        quality_details["score"] = 75
        ok, detail = _check_quality_gate(quality_details)
        assert ok is False

    def test_check_youtube_optimization(self):
        from phase2_validator import _check_youtube_optimization
        metadata = {
            "titles": ["Title1"],
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
            "chapters": [{"time": "0:00", "title": "Intro"}]
        }
        ok, detail = _check_youtube_optimization(metadata)
        assert ok is True

        # タグが足りない場合
        metadata["tags"] = ["tag1"]
        ok, detail = _check_youtube_optimization(metadata)
        assert ok is False



# ==========================================
# phase2_10run.py のテスト
# ==========================================

class TestPhase210Run:

    @patch("requests.get")
    @patch("time.sleep")
    def test_wait_for_idle_immediate(self, mock_sleep, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "idle"}
        mock_get.return_value = mock_resp
        
        assert phase2_10run.wait_for_idle() is True
        mock_sleep.assert_not_called()

    @patch("requests.get")
    @patch("time.sleep")
    def test_wait_for_idle_after_waiting(self, mock_sleep, mock_get):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {"status": "running"}
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"status": "completed"}
        
        mock_get.side_effect = [mock_resp1, mock_resp2]
        
        assert phase2_10run.wait_for_idle() is True
        assert mock_sleep.call_count == 1

    @patch("requests.get")
    @patch("time.sleep")
    def test_wait_for_idle_timeout(self, mock_sleep, mock_get):
        mock_get.side_effect = Exception("connection error")
        
        assert phase2_10run.wait_for_idle() is False
        assert mock_sleep.call_count == 60

    @patch("requests.post")
    def test_start_pipeline(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"session_id": "test_session"}
        mock_post.return_value = mock_resp
        
        res = phase2_10run.start_pipeline()
        assert res == {"session_id": "test_session"}

    @patch("requests.get")
    @patch("time.sleep")
    def test_wait_for_completion_success(self, mock_sleep, mock_get):
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = {"status": "running"}
        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = {"status": "completed", "result": {}}
        mock_get.side_effect = [mock_resp1, mock_resp2]
        
        res = phase2_10run.wait_for_completion()
        assert res == {"status": "completed", "result": {}}
        assert mock_sleep.call_count == 1

    @patch("requests.get")
    @patch("time.sleep")
    def test_wait_for_completion_error_status(self, mock_sleep, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "error", "error": "fatal"}
        mock_get.return_value = mock_resp
        
        res = phase2_10run.wait_for_completion()
        assert res == {"status": "error", "error": "fatal"}

    @patch("requests.get")
    @patch("time.sleep")
    @patch("time.time")
    def test_wait_for_completion_timeout(self, mock_time, mock_sleep, mock_get):
        # time.time() をモックしてタイムアウトさせる
        # 最初は 0、次は 200 (MAX_WAIT=180 を超える)
        mock_time.side_effect = [0.0, 0.0, 200.0]
        mock_get.side_effect = Exception("connection error")
        
        res = phase2_10run.wait_for_completion()
        assert res is None

    @patch("phase2_10run.start_pipeline")
    def test_run_single_test_start_failure(self, mock_start):
        mock_start.side_effect = Exception("failed to start")
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is False
        assert "起動失敗" in msg

    @patch("phase2_10run.start_pipeline")
    @patch("phase2_10run.wait_for_completion")
    def test_run_single_test_timeout(self, mock_wait, mock_start):
        mock_start.return_value = {"session_id": "test_session_id"}
        mock_wait.return_value = None
        
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is False
        assert msg == "タイムアウト"

    @patch("phase2_10run.start_pipeline")
    @patch("phase2_10run.wait_for_completion")
    def test_run_single_test_error_status(self, mock_wait, mock_start):
        mock_start.return_value = {"session_id": "test_session_id"}
        mock_wait.return_value = {"status": "error", "error": "mock error details"}
        
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is False
        assert "エラー: mock error details" in msg

    @patch("phase2_10run.start_pipeline")
    @patch("phase2_10run.wait_for_completion")
    @patch("phase2_10run.run_checks")
    def test_run_single_test_checks_pass(self, mock_checks, mock_wait, mock_start):
        mock_start.return_value = {"session_id": "test_session_id"}
        mock_wait.return_value = {"status": "completed", "result": {"quality_score": 95, "duration_seconds": 30}}
        mock_checks.return_value = [("Check 1", True, "ok"), ("Check 2", True, "ok")]
        
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is True
        assert "score=95" in msg

    @patch("phase2_10run.start_pipeline")
    @patch("phase2_10run.wait_for_completion")
    @patch("phase2_10run.run_checks")
    def test_run_single_test_checks_fail(self, mock_checks, mock_wait, mock_start):
        mock_start.return_value = {"session_id": "test_session_id"}
        mock_wait.return_value = {"status": "completed", "result": {"quality_score": 60, "duration_seconds": 30}}
        mock_checks.return_value = [("Check 1", True, "ok"), ("Check 2", False, "failed")]
        
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is False
        assert "score=60" in msg

    @patch("requests.get")
    def test_main_backend_offline(self, mock_get):
        mock_get.side_effect = Exception("backend down")
        
        with patch("builtins.print") as mock_print:
            passed = phase2_10run.main()
            assert passed is None
            # "バックエンドに接続できません" が出力されているか
            any_offline_msg = any("バックエンドに接続できません" in call[0][0] for call in mock_print.call_args_list)
            assert any_offline_msg is True

    @patch("requests.get")
    @patch("phase2_10run.wait_for_idle")
    def test_main_wait_for_idle_timeout(self, mock_idle, mock_get):
        mock_get.return_value = MagicMock()
        mock_idle.return_value = False
        
        passed = phase2_10run.main()
        assert passed is False

    @patch("requests.get")
    @patch("phase2_10run.wait_for_idle")
    @patch("phase2_10run.run_single_test")
    @patch("time.sleep")
    def test_main_10_runs_all_pass(self, mock_sleep, mock_run, mock_idle, mock_get):
        mock_get.return_value = MagicMock()
        mock_idle.return_value = True
        mock_run.return_value = (True, "score=90, duration=10s")
        
        passed = phase2_10run.main()
        assert passed is True
        assert mock_run.call_count == 10
        assert mock_sleep.call_count == 9  # ループ間のクールダウン 9回

    @patch("requests.get")
    @patch("phase2_10run.wait_for_idle")
    @patch("phase2_10run.run_single_test")
    @patch("time.sleep")
    def test_main_10_runs_with_some_failures(self, mock_sleep, mock_run, mock_idle, mock_get):
        mock_get.return_value = MagicMock()
        mock_idle.return_value = True
        # 1回目は失敗、それ以外は成功
        mock_run.side_effect = [(False, "timeout")] + [(True, "score=90, duration=10s")] * 9
        
        passed = phase2_10run.main()
        assert passed is False
        assert mock_run.call_count == 10

    @patch("phase2_10run.start_pipeline")
    @patch("phase2_10run.wait_for_completion")
    @patch("phase2_10run.run_checks")
    def test_run_single_test_unknown_status(self, mock_checks, mock_wait, mock_start):
        mock_start.return_value = {"session_id": "test_session_id"}
        mock_wait.return_value = {"status": "unknown_status", "result": {"quality_score": 80, "duration_seconds": 45}}
        mock_checks.return_value = [("Check 1", True, "ok")]
        
        ok, msg = phase2_10run.run_single_test(1)
        assert ok is True
        assert "score=80" in msg

    @patch("requests.get")
    @patch("phase2_10run.wait_for_idle")
    @patch("phase2_10run.run_single_test")
    @patch("time.sleep")
    def test_main_all_runs_fail(self, mock_sleep, mock_run, mock_idle, mock_get):
        mock_get.return_value = MagicMock()
        mock_idle.return_value = True
        mock_run.return_value = (False, "error")
        
        passed = phase2_10run.main()
        assert passed is False
        assert mock_run.call_count == 10

    @patch("builtins.print")
    def test_log_run_start(self, mock_print):
        phase2_10run._log_run_start(5)
        assert any("Run 5/10" in call[0][0] for call in mock_print.call_args_list)

    @patch("phase2_10run.start_pipeline")
    def test_start_pipeline_safely_success(self, mock_start):
        mock_start.return_value = {"session_id": "success_session"}
        ok, res = phase2_10run._start_pipeline_safely()
        assert ok is True
        assert res["session_id"] == "success_session"

    @patch("phase2_10run.start_pipeline")
    def test_start_pipeline_safely_failure(self, mock_start):
        mock_start.side_effect = Exception("conn error")
        ok, res = phase2_10run._start_pipeline_safely()
        assert ok is False
        assert "起動失敗: conn error" in res

    @patch("phase2_10run.run_checks")
    def test_evaluate_pipeline_result_success(self, mock_checks):
        mock_checks.return_value = [("Check 1", True, "ok")]
        data = {"result": {"quality_score": 90, "duration_seconds": 15}}
        ok, detail = phase2_10run._evaluate_pipeline_result(data)
        assert ok is True
        assert "score=90" in detail

    @patch("phase2_10run.run_checks")
    def test_evaluate_pipeline_result_failure(self, mock_checks):
        mock_checks.return_value = [("Check 1", False, "ng")]
        data = {"result": {"quality_score": 50, "duration_seconds": 15}}
        ok, detail = phase2_10run._evaluate_pipeline_result(data)
        assert ok is False
        assert "score=50" in detail

    @patch("requests.get")
    def test_check_backend_online_success(self, mock_get):
        mock_get.return_value = MagicMock()
        assert phase2_10run._check_backend_online() is True

    @patch("requests.get")
    def test_check_backend_online_failure(self, mock_get):
        mock_get.side_effect = Exception("offline")
        assert phase2_10run._check_backend_online() is False

