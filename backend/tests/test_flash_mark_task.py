import sys
import os
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch

# プロジェクトルートおよび backend を sys.path に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import flash_mark_task

def test_main_pass(capsys):
    test_args = [
        "flash_mark_task.py",
        "--conversation-id", "conv-123",
        "--task-id", "task-123",
        "--result", "pass",
        "--message", "Task passed successfully",
        "--changed-files", "file1.py, file2.py",
    ]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.flash_mark_task.OrchestrationHub", return_value=mock_hub_instance):
            flash_mark_task.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-123")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "task-123",
        "pass",
        {
            "message": "Task passed successfully",
            "changed_files": ["file1.py", "file2.py"]
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Marking task task-123 as pass..." in captured.out
    assert "mock_status_string" in captured.out

def test_main_fail(capsys):
    test_args = [
        "flash_mark_task.py",
        "--conversation-id", "conv-123",
        "--task-id", "task-123",
        "--result", "fail",
        "--error", "Some error details",
    ]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.flash_mark_task.OrchestrationHub", return_value=mock_hub_instance):
            flash_mark_task.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-123")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "task-123",
        "fail",
        {
            "error": "Some error details"
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Marking task task-123 as fail..." in captured.out
    assert "mock_status_string" in captured.out

def test_main_skip_mapping(capsys):
    test_args = [
        "flash_mark_task.py",
        "--conversation-id", "conv-123",
        "--task-id", "task-123",
        "--result", "skip",
    ]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.flash_mark_task.OrchestrationHub", return_value=mock_hub_instance):
            flash_mark_task.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-123")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "task-123",
        "skipped",
        {}
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Marking task task-123 as skipped..." in captured.out
    assert "mock_status_string" in captured.out

def test_main_skipped_direct(capsys):
    test_args = [
        "flash_mark_task.py",
        "--conversation-id", "conv-123",
        "--task-id", "task-123",
        "--result", "skipped",
    ]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "mock_status_string"}
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.flash_mark_task.OrchestrationHub", return_value=mock_hub_instance):
            flash_mark_task.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-123")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "task-123",
        "skipped",
        {}
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Marking task task-123 as skipped..." in captured.out
    assert "mock_status_string" in captured.out

def test_main_insufficient_arguments():
    test_args = ["flash_mark_task.py", "--task-id", "task-123"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit):
            flash_mark_task.main()

def test_main_as_script(capsys):
    test_args = ["flash_mark_task.py", "--conversation-id", "conv-123", "--task-id", "task-123", "--result", "invalid_status"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit):
            runpy.run_module("backend.agents.orchestration.flash_mark_task", run_name="__main__")
