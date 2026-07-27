import os
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_batch_449dfb

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_449dfb.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_batch_449dfb.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    mock_hub_instance.flash_update_heartbeat.assert_called()
    
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    expected_task_ids = [
        "T-batch_449dfb-test_weaver-000",
        "T-batch_449dfb-refactor-000",
        "T-batch_449dfb-test_weaver-001",
        "T-batch_449dfb-thumbnail-000",
        "T-batch_449dfb-thumbnail-001",
        "T-batch_449dfb-bug_hunter-000"
    ]
    
    for task_id in expected_task_ids:
        called_args_list = [call[0][0] for call in mock_hub_instance.mark_task_done.call_args_list]
        assert task_id in called_args_list
        
    captured = capsys.readouterr()
    for task_id in expected_task_ids:
        assert f"Marked {task_id} as pass" in captured.out
    assert "FLASH_STATUS_OK" in captured.out
    
    # submit_batch_reportの呼び出しを検証
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_449dfb",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
    )

def test_main_hub_exception_error_logging(capsys):
    """Verify that exceptions in main output error logs to stderr."""
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = Exception("Hub Process Error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_449dfb.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            try:
                mark_tasks_p27_batch_449dfb.main()
            except Exception as e:
                assert str(e) == "Hub Process Error"
                
    captured = capsys.readouterr()
    assert "Error occurred:" in captured.err
    assert "Hub Process Error" in captured.err

def test_main_hub_exception_technical_debt_registration():
    """Verify that exceptions trigger technical debt registration when FORCE_DEBT_REGISTRATION is set."""
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = Exception("Hub Process Error")
    
    mock_store_instance = MagicMock()
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_449dfb.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_instance), \
         patch.dict(os.environ, {"FORCE_DEBT_REGISTRATION": "1"}):
        try:
            mark_tasks_p27_batch_449dfb.main()
        except Exception as e:
            assert str(e) == "Hub Process Error"
            
    mock_store_instance.register_debt.assert_called_once()
    called_kwargs = mock_store_instance.register_debt.call_args[1]
    assert called_kwargs["category"] == "ACCEPTED_SAFETY"
    assert "mark_tasks_p27_batch_449dfb.py" in called_kwargs["file_path"]
    assert called_kwargs["pattern"] == "except Exception as e:"

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "SCRIPT_OK"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_449dfb.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_449dfb.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    mock_hub_instance.flash_update_heartbeat.assert_called()
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    captured = capsys.readouterr()
    assert "SCRIPT_OK" in captured.out
    
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_449dfb",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
    )
