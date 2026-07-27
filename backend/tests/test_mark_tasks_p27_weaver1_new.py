# -*- coding: utf-8 -*-
import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_weaver1_new

def test_setup_orchestration_hub():
    mock_hub_instance = MagicMock()
    with patch.object(mark_tasks_p27_weaver1_new, 'OrchestrationHub', return_value=mock_hub_instance):
        hub = mark_tasks_p27_weaver1_new.setup_orchestration_hub('test_conv_id')
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with('test_conv_id')

def test_build_completion_report():
    report = mark_tasks_p27_weaver1_new.build_completion_report(['file1'], 'msg1')
    assert report == {
        'message': 'msg1',
        'changed_files': ['file1']
    }

def test_submit_task_completion(capsys):
    mock_hub = MagicMock()
    report = {'message': 'msg1', 'changed_files': ['file1']}
    mark_tasks_p27_weaver1_new.submit_task_completion(mock_hub, 'task_1', report)
    mock_hub.mark_task_done.assert_called_once_with('task_1', 'pass', report)
    captured = capsys.readouterr()
    assert 'TASK_MARKED_DONE' in captured.out

def test_format_flash_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {'status': 'ok'}
    status_str = mark_tasks_p27_weaver1_new.format_flash_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    assert status_str == 'FLASH_STATUS:{"status": "ok"}'

def test_display_status(capsys):
    mark_tasks_p27_weaver1_new.display_status('test_msg')
    captured = capsys.readouterr()
    assert captured.out == "test_msg\n"

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {'formatted': 'mock_status_string'}

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        # sys.exit(0) が呼ばれることを期待
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 0

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with('a9736a64-a242-485f-942e-bf8476d21fa6')
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()

def test_main_exception_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("Unexpected error: Mock Network Error")
    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Network Error" in captured.err

def test_main_file_not_found_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = FileNotFoundError("Mock File Not Found")

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("FileNotFoundError: Mock File Not Found")
    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err

def test_main_json_decode_error_handling(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = json.JSONDecodeError("Mock JSON Error", "doc", 0)

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    mock_hub_instance.flash_report_error.assert_called_once_with("JSONDecodeError: Mock JSON Error: line 1 column 1 (char 0)")
    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err

def test_main_exception_when_hub_is_none(capsys):
    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.setup_orchestration_hub', side_effect=ValueError("Setup Fail")):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during marking tasks: Setup Fail" in captured.err


def test_main_file_not_found_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = FileNotFoundError("Mock File Not Found")
    mock_hub_instance.flash_report_error.side_effect = RuntimeError("Hub Report Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err

def test_main_json_decode_error_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = json.JSONDecodeError("Mock JSON Error", "doc", 0)
    mock_hub_instance.flash_report_error.side_effect = RuntimeError("Hub Report Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err

def test_main_exception_handling_with_hub_error(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Mock Network Error")
    mock_hub_instance.flash_report_error.side_effect = RuntimeError("Hub Report Error")

    with patch('backend.agents.orchestration.mark_tasks_p27_weaver1_new.OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error during marking tasks: Mock Network Error" in captured.err


def test_main_as_script():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {}

    # 実行前に sys.modules から削除して警告を抑止
    import sys
    sys.modules.pop('backend.agents.orchestration.mark_tasks_p27_weaver1_new', None)

    with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance):
        # runpy は SystemExit(0) をスローするはず
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module('backend.agents.orchestration.mark_tasks_p27_weaver1_new', run_name='__main__')
        assert exit_info.value.code == 0

    mock_hub_instance.register_flash_conversation_id.assert_called_once()
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once()



def test_main_file_not_found_when_hub_is_none(capsys):
    with patch.object(mark_tasks_p27_weaver1_new, 'setup_orchestration_hub', side_effect=FileNotFoundError("Mock File Not Found")):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Configuration or task queue file not found: Mock File Not Found" in captured.err

def test_main_json_decode_error_when_hub_is_none(capsys):
    mock_json_error = json.JSONDecodeError("Mock JSON Error", "doc", 0)
    with patch.object(mark_tasks_p27_weaver1_new, 'setup_orchestration_hub', side_effect=mock_json_error):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 1

    captured = capsys.readouterr()
    assert "Critical error: Failed to parse configuration or state JSON" in captured.err


def test_setup_orchestration_hub_edge_cases():
    mock_hub_instance = MagicMock()
    with patch.object(mark_tasks_p27_weaver1_new, 'OrchestrationHub', return_value=mock_hub_instance):
        hub = mark_tasks_p27_weaver1_new.setup_orchestration_hub(None)
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with(None)

        mock_hub_instance.reset_mock()
        hub2 = mark_tasks_p27_weaver1_new.setup_orchestration_hub("")
        assert hub2 == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("")


def test_build_completion_report_edge_cases():
    report1 = mark_tasks_p27_weaver1_new.build_completion_report([], "")
    assert report1 == {
        'message': '',
        'changed_files': []
    }
    
    report2 = mark_tasks_p27_weaver1_new.build_completion_report(None, None)
    assert report2 == {
        'message': None,
        'changed_files': None
    }

    huge_files = ["file_" + str(i) for i in range(10000)]
    huge_message = "A" * 1000000
    report3 = mark_tasks_p27_weaver1_new.build_completion_report(huge_files, huge_message)
    assert len(report3['changed_files']) == 10000
    assert len(report3['message']) == 1000000


def test_submit_task_completion_edge_cases():
    mock_hub = MagicMock()
    mark_tasks_p27_weaver1_new.submit_task_completion(mock_hub, "", {})
    mock_hub.mark_task_done.assert_called_once_with("", 'pass', {})
    
    mock_hub.reset_mock()
    mark_tasks_p27_weaver1_new.submit_task_completion(mock_hub, None, None)
    mock_hub.mark_task_done.assert_called_once_with(None, 'pass', None)


def test_format_flash_status_edge_cases():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = None
    status_str = mark_tasks_p27_weaver1_new.format_flash_status(mock_hub)
    assert status_str == 'FLASH_STATUS:null'

    mock_hub.generate_flash_status.return_value = {}
    status_str2 = mark_tasks_p27_weaver1_new.format_flash_status(mock_hub)
    assert status_str2 == 'FLASH_STATUS:{}'


def test_display_status_edge_cases(capsys):
    mark_tasks_p27_weaver1_new.display_status("")
    captured = capsys.readouterr()
    assert captured.out == "\n"

    mark_tasks_p27_weaver1_new.display_status(None)
    captured = capsys.readouterr()
    assert captured.out == "None\n"



def test_submit_task_completion_raises_exception():
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = RuntimeError("Mark Done Failed")
    with pytest.raises(RuntimeError) as exc_info:
        mark_tasks_p27_weaver1_new.submit_task_completion(mock_hub, 'task_1', {})
    assert "Mark Done Failed" in str(exc_info.value)


def test_constants():
    assert mark_tasks_p27_weaver1_new.TARGET_TASK_ID == "T-batch_a97ee3-test_weaver-001"
    assert mark_tasks_p27_weaver1_new.FLASH_CONVERSATION_ID == "a9736a64-a242-485f-942e-bf8476d21fa6"


def test_main_call_order():
    mock_hub_instance = MagicMock()
    
    manager = MagicMock()
    mock_hub_instance.flash_update_heartbeat = manager.flash_update_heartbeat
    mock_hub_instance.mark_task_done = manager.mark_task_done
    mock_hub_instance.generate_flash_status = manager.generate_flash_status
    manager.generate_flash_status.return_value = {}
    
    with patch.object(mark_tasks_p27_weaver1_new, 'OrchestrationHub', return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as exit_info:
            mark_tasks_p27_weaver1_new.main()
        assert exit_info.value.code == 0
        
    calls = manager.mock_calls
    assert len(calls) >= 3
    assert calls[0][0] == 'flash_update_heartbeat'
    assert calls[1][0] == 'mark_task_done'
    assert calls[2][0] == 'generate_flash_status'


def test_display_status_multibyte_and_newlines(capsys):
    multibyte_str = "こんにちは、世界！\n🌟🚀\nNew Line Test"
    mark_tasks_p27_weaver1_new.display_status(multibyte_str)
    captured = capsys.readouterr()
    assert captured.out == "こんにちは、世界！\n🌟🚀\nNew Line Test\n"


def test_setup_orchestration_hub_invalid_types():
    mock_hub_instance = MagicMock()
    with patch.object(mark_tasks_p27_weaver1_new, 'OrchestrationHub', return_value=mock_hub_instance):
        # リストや辞書などの不正な型を渡す
        hub1 = mark_tasks_p27_weaver1_new.setup_orchestration_hub(["invalid_id"])
        mock_hub_instance.register_flash_conversation_id.assert_called_with(["invalid_id"])
        
        hub2 = mark_tasks_p27_weaver1_new.setup_orchestration_hub({"id": 123})
        mock_hub_instance.register_flash_conversation_id.assert_called_with({"id": 123})


def test_format_flash_status_non_serializable():
    mock_hub = MagicMock()
    # set は JSON シリアライズ不可能なので TypeError が発生するはず
    mock_hub.generate_flash_status.return_value = {1, 2, 3}
    with pytest.raises(TypeError):
        mark_tasks_p27_weaver1_new.format_flash_status(mock_hub)


def test_build_completion_report_unusual_types():
    # 本来 List[str] と str を想定しているが、tuple や dict などを渡した場合の挙動
    report = mark_tasks_p27_weaver1_new.build_completion_report(
        ("file1.py", "file2.py"),
        {"text": "message_dict"}
    )
    assert report == {
        'message': {"text": "message_dict"},
        'changed_files': ("file1.py", "file2.py")
    }

