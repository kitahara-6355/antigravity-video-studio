import sys
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_refactor0

def test_setup_orchestration_hub():
    mock_hub_instance = MagicMock()
    with patch('backend.agents.orchestration.mark_tasks_p27_refactor0.OrchestrationHub', return_value=mock_hub_instance):
        hub = mark_tasks_p27_refactor0.setup_orchestration_hub('test_conv_id')
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with('test_conv_id')

def test_build_completion_report():
    report = mark_tasks_p27_refactor0.build_completion_report(['file1'], 'msg1')
    assert report == {
        'message': 'msg1',
        'changed_files': ['file1']
    }

def test_submit_task_completion(capsys):
    mock_hub = MagicMock()
    report = {'message': 'msg1', 'changed_files': ['file1']}
    mark_tasks_p27_refactor0.submit_task_completion(mock_hub, 'task_1', report)
    mock_hub.mark_task_done.assert_called_once_with('task_1', 'pass', report)
    captured = capsys.readouterr()
    assert 'TASK_MARKED_DONE' in captured.out

def test_format_flash_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {'status': 'ok'}
    status_str = mark_tasks_p27_refactor0.format_flash_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    assert status_str == 'FLASH_STATUS:{"status": "ok"}'

def test_display_status(capsys):
    mark_tasks_p27_refactor0.display_status('test_msg')
    captured = capsys.readouterr()
    assert captured.out == "test_msg\n"

def test_main(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {'formatted': 'mock_status_string'}

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor0.OrchestrationHub', return_value=mock_hub_instance):
        mark_tasks_p27_refactor0.main()

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with('819c8bbd-e916-476d-b8a1-8582dedb4659')
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()

def test_main_as_script():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}

    with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance):
        runpy.run_module('backend.agents.orchestration.mark_tasks_p27_refactor0', run_name='__main__')

    mock_hub_instance.register_flash_conversation_id.assert_called_once()
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()
