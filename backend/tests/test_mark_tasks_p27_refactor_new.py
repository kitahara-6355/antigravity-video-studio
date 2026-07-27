# -*- coding: utf-8 -*-
import sys
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_refactor_new

def test_setup_orchestration_hub():
    mock_hub_instance = MagicMock()
    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        hub = mark_tasks_p27_refactor_new.setup_orchestration_hub('test_conv_id')
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with('test_conv_id')

def test_build_completion_report():
    report = mark_tasks_p27_refactor_new.build_completion_report(['file1'], 'msg1')
    assert report == {
        'message': 'msg1',
        'changed_files': ['file1']
    }

def test_submit_task_completion(capsys):
    mock_hub = MagicMock()
    report = {'message': 'msg1', 'changed_files': ['file1']}
    mark_tasks_p27_refactor_new.submit_task_completion(mock_hub, 'task_1', report)
    mock_hub.mark_task_done.assert_called_once_with('task_1', 'pass', report)
    captured = capsys.readouterr()
    assert 'TASK_MARKED_DONE' in captured.out

def test_format_flash_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {'status': 'ok'}
    status_str = mark_tasks_p27_refactor_new.format_flash_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    assert status_str == 'FLASH_STATUS:{"status": "ok"}'

def test_display_status(capsys):
    mark_tasks_p27_refactor_new.display_status('test_msg')
    captured = capsys.readouterr()
    assert captured.out == "test_msg\n"

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {'formatted': 'mock_status_string'}

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        # sys.exit(0) が呼ばれることを期待
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 0

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with('a9736a64-a242-485f-942e-bf8476d21fa6')
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()

def test_main_exception_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        # sys.exit(1) が呼ばれることを期待
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Runtime error during marking tasks: Mock Network Error" in captured.err

def test_main_os_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = OSError("Mock OS Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "File I/O error during marking tasks: Mock OS Error" in captured.err

def test_main_json_error(capsys):
    mock_hub_instance = MagicMock()
    import json
    mock_hub_instance.flash_update_heartbeat.side_effect = json.JSONDecodeError("Mock JSON Error", "doc", 0)

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "JSON format error during marking tasks:" in captured.err

def test_main_key_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = KeyError("Mock Key Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Missing key error during marking tasks:" in captured.err

def test_main_value_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Mock Value Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Invalid value or type error during marking tasks: Mock Value Error" in captured.err

def test_main_type_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = TypeError("Mock Type Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_refactor_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_refactor_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Invalid value or type error during marking tasks: Mock Type Error" in captured.err

def test_main_as_script():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}

    # Remove the module from sys.modules to prevent RuntimeWarning when executing via runpy
    import sys
    sys.modules.pop('backend.agents.orchestration.mark_tasks_p27_refactor_new', None)

    with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance):
        # runpy は SystemExit(0) をスローするはず
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module('backend.agents.orchestration.mark_tasks_p27_refactor_new', run_name='__main__')
        assert exit_info.value.code == 0

    mock_hub_instance.register_flash_conversation_id.assert_called_once()
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()

