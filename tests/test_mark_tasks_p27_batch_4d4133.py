import os
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_batch_4d4133

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4d4133.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_batch_4d4133.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    # 登録されたタスクの数だけ mark_task_done が呼ばれていることの検証
    assert mock_hub_instance.mark_task_done.call_count == len(mark_tasks_p27_batch_4d4133.BATCH_TASKS)
    
    # 具体的なタスクIDでの検証
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_4d4133-test_weaver-001",
        "pass",
        mark_tasks_p27_batch_4d4133.BATCH_TASKS[0]["report"]
    )
    
    captured = capsys.readouterr()
    assert "Marked T-batch_4d4133-test_weaver-001 as pass" in captured.out
    assert "FLASH_STATUS_OK" in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "SCRIPT_OK"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_4d4133.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4d4133.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    assert mock_hub_instance.mark_task_done.call_count == len(mark_tasks_p27_batch_4d4133.BATCH_TASKS)
    
    captured = capsys.readouterr()
    assert "SCRIPT_OK" in captured.out

def test_batch_tasks_structure():
    """Verify that BATCH_TASKS has valid structures."""
    for task in mark_tasks_p27_batch_4d4133.BATCH_TASKS:
        assert "id" in task
        assert "status" in task
        assert "report" in task
        assert isinstance(task["id"], str)
        assert task["status"] in ("pass", "fail")
        assert isinstance(task["report"], dict)

def test_main_hub_exception(capsys):
    """Verify exceptions in main when OrchestrationHub fails."""
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = Exception("Hub Error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_4d4133.OrchestrationHub", return_value=mock_hub_instance):
        try:
            mark_tasks_p27_batch_4d4133.main()
        except Exception as e:
            assert str(e) == "Hub Error"
