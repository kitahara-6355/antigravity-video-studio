import sys
import os
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

@pytest.fixture(autouse=True)
def clean_modules():
    module_name = "backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a"
    if module_name in sys.modules:
        del sys.modules[module_name]

def test_main_success(capsys):
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 0

    mock_hub.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_3f4c3a-thumbnail-001",
        "pass",
        {
            "subagent_id": "a175d4c0-b115-412a-aab8-472995264f3c",
            "message": "verify_image_gen.py 日本語自動折り返し対応、一時ファイル拡張子保持、極小解像度Glassmorphism背景ガード、自動検証テスト追加。",
            "changed_files": [
                "backend/verify_image_gen.py",
                "backend/tests/test_verify_image_gen.py"
            ]
        }
    )
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_3f4c3a",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6
        }
    )
    mock_hub.generate_flash_status.assert_called_once()
    captured = capsys.readouterr()
    assert "Marked T-batch_3f4c3a-thumbnail-001 as pass." in captured.out
    assert "Batch batch_3f4c3a report submitted successfully." in captured.out
    assert "mocked_status" in captured.out

def test_main_init_failure(capsys):
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.register_flash_conversation_id.side_effect = RuntimeError("Init failed")

        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 1

    captured = capsys.readouterr()
    assert "Error initializing OrchestrationHub: Init failed" in captured.err

def test_main_heartbeat_failure(capsys):
    mock_hub = MagicMock()
    mock_hub.flash_update_heartbeat.side_effect = RuntimeError("Heartbeat failed")

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 1

    captured = capsys.readouterr()
    assert "Error updating heartbeat: Heartbeat failed" in captured.err

def test_main_mark_task_failure(capsys):
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = RuntimeError("Mark task failed")

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 1

    captured = capsys.readouterr()
    assert "Error marking task done: Mark task failed" in captured.err

def test_main_submit_report_failure(capsys):
    mock_hub = MagicMock()
    mock_hub.submit_batch_report.side_effect = RuntimeError("Submit report failed")

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 1

    captured = capsys.readouterr()
    assert "Error submitting batch report: Submit report failed" in captured.err

def test_main_generate_status_failure(capsys):
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = RuntimeError("Status failed")

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete_3f4c3a import main
        result = main()
        assert result == 1

    captured = capsys.readouterr()
    assert "Error generating flash status: Status failed" in captured.err
