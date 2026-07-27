# -*- coding: utf-8 -*-
import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_weaver1

def test_setup_orchestration_hub():
    mock_hub_instance = MagicMock()
    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        hub = mark_tasks_p27_weaver1.setup_orchestration_hub('test_conv_id')
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with('test_conv_id')

def test_build_completion_report():
    report = mark_tasks_p27_weaver1.build_completion_report(['file1'], 'msg1')
    assert report == {
        'message': 'msg1',
        'changed_files': ['file1']
    }

def test_submit_task_completion(capsys):
    mock_hub = MagicMock()
    report = {'message': 'msg1', 'changed_files': ['file1']}
    mark_tasks_p27_weaver1.submit_task_completion(mock_hub, 'task_1', report)
    mock_hub.mark_task_done.assert_called_once_with('task_1', 'pass', report)
    captured = capsys.readouterr()
    assert 'TASK_MARKED_DONE' in captured.out

def test_format_flash_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {'status': 'ok'}
    status_str = mark_tasks_p27_weaver1.format_flash_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    assert status_str == 'FLASH_STATUS:{"status": "ok"}'

def test_display_status(capsys):
    mark_tasks_p27_weaver1.display_status('test_msg')
    captured = capsys.readouterr()
    assert captured.out == "test_msg\n"

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {'formatted': 'mock_status_string'}

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 0

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with('a9736a64-a242-485f-942e-bf8476d21fa6')
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()

def test_main_exception_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("Unexpected error: Mock Network Error")
    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Network Error" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_file_not_found_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = FileNotFoundError("Mock File Not Found")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("FileNotFoundError: Mock File Not Found")
    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_json_decode_error_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = json.JSONDecodeError("Mock JSON Error", "doc", 0)

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("JSONDecodeError: Mock JSON Error: line 1 column 1 (char 0)")
    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_exception_when_hub_is_none(capsys):
    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1.setup_orchestration_hub', side_effect=ValueError("Setup Fail")):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during marking tasks: Setup Fail" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_file_not_found_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = FileNotFoundError("Mock File Not Found")
    mock_hub_instance.flash_report_error.side_effect = OSError("Hub Report Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err
    assert "Failed to report error to hub: Hub Report Error" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_json_decode_error_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = json.JSONDecodeError("Mock JSON Error", "doc", 0)
    mock_hub_instance.flash_report_error.side_effect = OSError("Hub Report Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err
    assert "Failed to report error to hub: Hub Report Error" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_exception_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")
    mock_hub_instance.flash_report_error.side_effect = OSError("Hub Report Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Network Error" in captured.err
    assert "Failed to report error to hub: Hub Report Error" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_as_script():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}

    import sys
    orig_mod = sys.modules.get('backend.agents.orchestration.mark_tasks_p27_weaver1')
    sys.modules.pop('backend.agents.orchestration.mark_tasks_p27_weaver1', None)

    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as exit_info:
                runpy.run_module('backend.agents.orchestration.mark_tasks_p27_weaver1', run_name='__main__')
            assert exit_info.value.code == 0
    finally:
        if orig_mod:
            sys.modules['backend.agents.orchestration.mark_tasks_p27_weaver1'] = orig_mod

    mock_hub_instance.register_flash_conversation_id.assert_called_once()
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()

def test_main_file_not_found_when_hub_is_none(capsys):
    with patch.object(mark_tasks_p27_weaver1, 'setup_orchestration_hub', side_effect=FileNotFoundError("Mock File Not Found")):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_main_json_decode_error_when_hub_is_none(capsys):
    mock_json_error = json.JSONDecodeError("Mock JSON Error", "doc", 0)
    with patch.object(mark_tasks_p27_weaver1, 'setup_orchestration_hub', side_effect=mock_json_error):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err
    assert "Traceback (most recent call last):" in captured.err


def test_main_key_error_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = KeyError("Mock Key Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("Unexpected error: 'Mock Key Error'")
    captured = capsys.readouterr()
    assert "Error during marking tasks: 'Mock Key Error'" in captured.err

def test_main_type_error_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = TypeError("Mock Type Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("Unexpected error: Mock Type Error")
    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Type Error" in captured.err

def test_main_value_error_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Mock Value Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("Unexpected error: Mock Value Error")
    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Value Error" in captured.err

def test_main_exception_handling_with_hub_type_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")
    mock_hub_instance.flash_report_error.side_effect = TypeError("Hub Report Type Error")

    with patch.object(mark_tasks_p27_weaver1, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Network Error" in captured.err
    assert "Failed to report error to hub: Hub Report Type Error" in captured.err
