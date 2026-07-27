import sys
import os
import json
from unittest.mock import MagicMock, patch
import pytest

# 動的にプロジェクトルートを sys.path の先頭に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_mark_and_submit_batch2_main_success(capsys):
    import runpy
    if "backend.agents.orchestration.mark_and_submit_batch2" in sys.modules:
        del sys.modules["backend.agents.orchestration.mark_and_submit_batch2"]

    mock_hub = MagicMock()
    dummy_status = {"status": "running", "progress": 0.5}
    mock_hub.generate_flash_status.return_value = dummy_status

    original_path = sys.path.copy()
    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            runpy.run_module("backend.agents.orchestration.mark_and_submit_batch2", run_name="__main__")
    finally:
        sys.path = original_path

    mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_214e16-thumbnail-000",
        "pass",
        {
            "message": "verify_thumbnail_gen.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/verify_thumbnail_gen.py",
                "backend/tests/test_verify_thumbnail_gen.py"
            ]
        }
    )
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_214e16",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS:" in captured.out
