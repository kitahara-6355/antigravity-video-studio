import os
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_batch_d0e373

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_d0e373.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_batch_d0e373.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    expected_task_ids = [
        "T-batch_d0e373-test_weaver-000",
        "T-batch_d0e373-thumbnail-001",
        "T-batch_d0e373-test_weaver-001",
        "T-batch_d0e373-refactor-000",
        "T-batch_d0e373-bug_hunter-000",
        "T-batch_d0e373-thumbnail-000"
    ]
    
    for task_id in expected_task_ids:
        called_args_list = [call[0][0] for call in mock_hub_instance.mark_task_done.call_args_list]
        assert task_id in called_args_list
        
    captured = capsys.readouterr()
    for task_id in expected_task_ids:
        assert f"Marked {task_id} as pass" in captured.out
    assert "FLASH_STATUS_OK" in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "SCRIPT_OK"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_d0e373.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_d0e373.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    captured = capsys.readouterr()
    assert "SCRIPT_OK" in captured.out
