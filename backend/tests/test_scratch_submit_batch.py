import sys
import os
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

def test_backend_scratch_submit_batch_success(capsys):
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    dummy_status = {"status": "success", "detail": "all tests passed"}
    mock_hub.generate_flash_status.return_value = dummy_status

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            import backend.scratch.submit_batch
    finally:
        sys.path = original_path

    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_769699",
        {
            "passed": 18,
            "failed": 0,
            "skipped": 12,
            "total": 30
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "STATUS_START" in captured.out
    assert "STATUS_END" in captured.out
    assert '"status": "success"' in captured.out
    assert '"detail": "all tests passed"' in captured.out

def test_backend_scratch_submit_batch_exception():
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    mock_hub.flash_update_heartbeat.side_effect = Exception("Orchestrator Connection Refused")

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            with pytest.raises(Exception) as excinfo:
                import backend.scratch.submit_batch
            assert "Orchestrator Connection Refused" in str(excinfo.value)
    finally:
        sys.path = original_path


def test_backend_scratch_submit_batch_project_root_in_path():
    # プロジェクトルートが正しく sys.path に入っていることを確認するテスト
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    assert project_root in sys.path
