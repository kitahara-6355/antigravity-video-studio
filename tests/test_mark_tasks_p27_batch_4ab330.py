# -*- coding: utf-8 -*-
import os
import sys
import pytest
import runpy
from unittest.mock import MagicMock, patch

# テスト対象モジュールのインポートのためにパスを通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import mark_tasks_p27_batch_4ab330

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_batch_4ab330.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    assert mock_hub_instance.mark_task_done.call_count == len(mark_tasks_p27_batch_4ab330.TASKS_TO_MARK)
    
    # 具体的なタスクIDでの検証
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_4ab330-test_weaver-000",
        "pass",
        mark_tasks_p27_batch_4ab330.TASKS_TO_MARK[0]["report"]
    )
    
    captured = capsys.readouterr()
    assert "Marked T-batch_4ab330-test_weaver-000 as pass" in captured.out
    assert "FLASH_STATUS_OK" in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "SCRIPT_OK"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_4ab330.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    assert mock_hub_instance.mark_task_done.call_count == len(mark_tasks_p27_batch_4ab330.TASKS_TO_MARK)
    
    captured = capsys.readouterr()
    assert "SCRIPT_OK" in captured.out

def test_setup_orchestration_hub_failure():
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", side_effect=RuntimeError("Hub initialization error")):
        with pytest.raises(RuntimeError) as exc_info:
            mark_tasks_p27_batch_4ab330.setup_orchestration_hub("test_id")
        assert "Hub initialization error" in str(exc_info.value)

def test_extract_task_components_invalid():
    invalid_task = {"status": "pass"}  # task_id と report が欠けている
    with pytest.raises(KeyError):
        mark_tasks_p27_batch_4ab330.extract_task_components(invalid_task)

def test_extract_task_components_other_exception():
    # task_infoがNoneなどの場合、TypeErrorが発生するはず
    with pytest.raises(TypeError):
        mark_tasks_p27_batch_4ab330.extract_task_components(None)

def test_register_task_status_failure():
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = ValueError("Invalid status value")
    task_info = {
        "task_id": "test-id",
        "status": "invalid-status",
        "report": {"message": "test"}
    }
    with pytest.raises(ValueError) as exc_info:
        mark_tasks_p27_batch_4ab330.register_task_status(mock_hub, task_info)
    assert "Invalid status value" in str(exc_info.value)

def test_main_failure_exits(capsys):
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", side_effect=RuntimeError("Fatal error")):
        with pytest.raises(SystemExit) as exc_info:
            mark_tasks_p27_batch_4ab330.main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Execution failed in main" in captured.err

def test_setup_orchestration_hub_oserror(capsys):
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", side_effect=OSError("Disk full")):
        with pytest.raises(OSError) as exc_info:
            mark_tasks_p27_batch_4ab330.setup_orchestration_hub("test_id")
        assert "Disk full" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Failed to setup OrchestrationHub with conversation ID 'test_id': Disk full" in captured.err

def test_extract_task_components_typeerror(capsys):
    with pytest.raises(TypeError) as exc_info:
        mark_tasks_p27_batch_4ab330.extract_task_components(None)
    
    captured = capsys.readouterr()
    assert "Failed to extract task components" in captured.err

def test_register_task_status_keyerror(capsys):
    mock_hub = MagicMock()
    invalid_task = {"status": "pass"}
    with pytest.raises(KeyError) as exc_info:
        mark_tasks_p27_batch_4ab330.register_task_status(mock_hub, invalid_task)
    
    captured = capsys.readouterr()
    assert "Failed to register task status for task_info" in captured.err

def test_main_oserror_exit(capsys):
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub", side_effect=OSError("Read-only file system")):
        with pytest.raises(SystemExit) as exc_info:
            mark_tasks_p27_batch_4ab330.main()
        assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Execution failed in main" in captured.err

