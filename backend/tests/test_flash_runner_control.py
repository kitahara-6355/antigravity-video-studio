import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# テスト対象のモジュールがあるパスを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..", "backend")))

from backend.agents.orchestration.flash_runner_control import main

@pytest.fixture
def mock_hub():
    with patch("backend.agents.orchestration.flash_runner_control.OrchestrationHub") as mock:
        hub_instance = MagicMock()
        mock.return_value = hub_instance
        # 必要なモックメソッドの定義
        hub_instance.get_phase_state.return_value = {"current_phase": 33, "current_milestone": "M33.1"}
        hub_instance.get_next_batch.return_value = {"batch_id": "test_batch", "tasks": []}
        hub_instance.generate_flash_status.return_value = {"formatted": "Status OK"}
        yield hub_instance

def test_get_batch(mock_hub):
    test_args = ["flash_runner_control.py", "--conversation-id", "test-conv-123", "--get-batch"]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-123")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.get_next_batch.assert_called_once_with(phase=33, milestone="M33.1", batch_size=6)

def test_get_batch_with_specific_phase(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--get-batch", 
        "--phase", "30", 
        "--milestone", "M30.1"
    ]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.get_next_batch.assert_called_once_with(phase=30, milestone="M30.1", batch_size=6)

def test_mark_task(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--mark-task", 
        "--task-id", "task-abc", 
        "--task-status", "pass", 
        "--task-report", '{"result": "ok"}'
    ]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.mark_task_done.assert_called_once_with("task-abc", "pass", {"result": "ok"})

def test_mark_task_missing_args(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--mark-task", 
        "--task-id", "task-abc"
    ]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1

def test_submit_batch(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--submit-batch", 
        "--batch-id", "batch-123", 
        "--passed", "5", 
        "--failed", "0", 
        "--skipped", "1", 
        "--total", "6"
    ]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch-123", 
        {"passed": 5, "failed": 0, "skipped": 1, "total": 6}
    )

def test_session_end_with_reason(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--session-end", "Completed successfully"
    ]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.flash_session_end.assert_called_once_with("Completed successfully")

def test_session_end_with_empty_string(mock_hub):
    test_args = [
        "flash_runner_control.py", 
        "--conversation-id", "test-conv-123", 
        "--session-end", ""
    ]
    with patch.object(sys, "argv", test_args):
        main()
    
    mock_hub.flash_session_end.assert_called_once_with("")

def test_mark_task_with_valid_report_file(mock_hub, tmp_path):
    report_file = tmp_path / "valid_report.json"
    report_data = {"status": "success", "metrics": {"duration": 1.5}}
    
    import json
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f)
        
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123",
        "--mark-task",
        "--task-id", "task-xyz",
        "--task-status", "pass",
        "--task-report", str(report_file)
    ]
    with patch.object(sys, "argv", test_args):
        main()
        
    mock_hub.mark_task_done.assert_called_once_with("task-xyz", "pass", report_data)

def test_mark_task_with_invalid_json_file(mock_hub, tmp_path):
    report_file = tmp_path / "invalid_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("{invalid-json}")
        
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123",
        "--mark-task",
        "--task-id", "task-xyz",
        "--task-status", "pass",
        "--task-report", str(report_file)
    ]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1

def test_mark_task_with_oserror_file(mock_hub):
    # 存在するパスだが、オープンしようとすると OSError が発生するようなモック
    # patch で builtins.open に OSError を発生させる
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123",
        "--mark-task",
        "--task-id", "task-xyz",
        "--task-status", "pass",
        "--task-report", "dummy_file_path"
    ]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            with patch.object(sys, "argv", test_args):
                with pytest.raises(SystemExit) as excinfo:
                    main()
            assert excinfo.value.code == 1


def test_submit_batch_negative_counts(mock_hub):
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123",
        "--submit-batch",
        "--batch-id", "batch-123",
        "--passed", "-1",
        "--failed", "0",
        "--skipped", "1",
        "--total", "0"
    ]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


def test_submit_batch_invalid_total(mock_hub):
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123",
        "--submit-batch",
        "--batch-id", "batch-123",
        "--passed", "5",
        "--failed", "0",
        "--skipped", "0",
        "--total", "6"
    ]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1


def test_no_action_specified(mock_hub):
    test_args = [
        "flash_runner_control.py",
        "--conversation-id", "test-conv-123"
    ]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            main()
    assert excinfo.value.code == 1
