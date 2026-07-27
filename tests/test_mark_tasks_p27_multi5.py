import sys
import json
import os
import pytest
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルートディレクトリを sys.path に追加
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.agents.orchestration import mark_tasks_p27_multi5
from backend.agents.orchestration.hub_common import OpusQuotaExceededException

def test_main_success(capsys):
    # OrchestrationHub をモック
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # 正常系メイン関数テスト
    # モジュールのローカルバインドとパッケージグローバル両方をパッチして、インポート方法にかかわらずモック化する
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi5.main()
        
    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_394f90-tdr_cleanup-000",
        "fail",
        {
            "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."
        }
    )
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_394f90",
        {
            "passed": 2,
            "failed": 6,
            "skipped": 0,
            "total": 8,
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "ok"}' in captured.out

def test_main_as_script(capsys):
    # スクリプトとして直接実行された場合のテスト (__name__ == "__main__")
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "script_ok"}
    
    # runpy.run_pathを使用して直接ファイルを実行し、RuntimeWarningを回避する
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi5.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_394f90-tdr_cleanup-000",
        "fail",
        {
            "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."
        }
    )
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_394f90",
        {
            "passed": 2,
            "failed": 6,
            "skipped": 0,
            "total": 8,
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "script_ok"}' in captured.out

def test_main_hub_exception(capsys):
    # OrchestrationHubで例外が発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Hub process error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main()
    
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Value error occurred: Hub process error" in captured.err
    mock_hub_instance.flash_report_error.assert_called_once_with(
        "ValueError: Hub process error", module="mark_tasks_p27_multi5"
    )


def test_main_hub_type_error(capsys):
    # mark_task_doneでTypeErrorが発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.mark_task_done.side_effect = TypeError("Invalid argument type")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main()
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Type error occurred: Invalid argument type" in captured.err
    mock_hub_instance.flash_report_error.assert_called_once_with(
        "TypeError: Invalid argument type", module="mark_tasks_p27_multi5"
    )


def test_main_hub_report_error_exception(capsys):
    # flash_report_error 自体が例外をスローした場合でも、元のエラーが処理され終了コード1になることをテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Hub process error")
    mock_hub_instance.flash_report_error.side_effect = RuntimeError("Failed to write log")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main()
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Value error occurred: Hub process error" in captured.err
    mock_hub_instance.flash_report_error.assert_called_once_with(
        "ValueError: Hub process error", module="mark_tasks_p27_multi5"
    )


def test_main_import_error(capsys):
    # インポート時に ImportError が発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=ImportError("Import failed")):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Import error occurred: Import failed" in captured.err


def test_main_key_error(capsys):
    # KeyErrorが発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=KeyError("Key missing")):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Key error occurred: 'Key missing'" in captured.err


def test_main_generic_exception(capsys):
    # setup_orchestration_hub で RuntimeError (generic Exception) が発生した場合に
    # 適切に終了コード 1 で終了し、メッセージが出力されることをテスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=RuntimeError("Generic runtime error")):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error occurred during batch task processing: Generic runtime error" in captured.err


def test_main_json_decode_error(capsys):
    # json.JSONDecodeError が発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    import json
    err = json.JSONDecodeError("Expecting value", "{}", 0)
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=err):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "JSON decode error occurred: Expecting value: line 1 column 1 (char 0)" in captured.err


def test_main_file_not_found_error(capsys):
    # FileNotFoundError が発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=FileNotFoundError("Session file missing")):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Required file not found: Session file missing" in captured.err


def test_main_os_error(capsys):
    # OSError が発生した場合に適切に終了コード1で終了し、メッセージが出力されることをテスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.setup_orchestration_hub", side_effect=OSError("Disk full")):
        with pytest.raises(SystemExit) as excinfo:
            mark_tasks_p27_multi5.main()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "OS error occurred: Disk full" in captured.err


def test_sys_path_insertion():
    # sys.path に project_root や backend_dir が含まれていない場合に sys.path.insert が実行されることをテスト
    import sys
    import importlib
    
    current_dir = os.path.dirname(os.path.abspath(mark_tasks_p27_multi5.__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    backend_dir = os.path.join(project_root, "backend")
    
    original_path = list(sys.path)
    
    try:
        sys.path = [p for p in sys.path if p != project_root and p != backend_dir]
        
        importlib.reload(mark_tasks_p27_multi5)
        
        assert project_root in sys.path
        assert backend_dir in sys.path
    finally:
        sys.path = original_path


@pytest.mark.parametrize(
    "exception_type, exception_inst, expected_err_msg, expected_report_prefix",
    [
        (json.JSONDecodeError, json.JSONDecodeError("Expecting value", "{}", 0), "JSON decode error occurred", "JSONDecodeError"),
        (FileNotFoundError, FileNotFoundError("Session missing"), "Required file not found", "FileNotFoundError"),
        (OSError, OSError("Disk full"), "OS error occurred", "OSError"),
        (ImportError, ImportError("Module missing"), "Import error occurred", "ImportError"),
        (ValueError, ValueError("Invalid value"), "Value error occurred", "ValueError"),
        (TypeError, TypeError("Invalid type"), "Type error occurred", "TypeError"),
        (KeyError, KeyError("Key missing"), "Key error occurred", "KeyError"),
        (RuntimeError, RuntimeError("Unexpected error"), "Unexpected error occurred during batch task processing", "UnexpectedError"),
    ]
)
def test_main_hub_post_init_exceptions(capsys, exception_type, exception_inst, expected_err_msg, expected_report_prefix):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = exception_inst
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main()
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert expected_err_msg in captured.err
    mock_hub_instance.flash_report_error.assert_called_once()
    args, kwargs = mock_hub_instance.flash_report_error.call_args
    assert args[0].startswith(expected_report_prefix)
    assert kwargs.get("module") == "mark_tasks_p27_multi5"


def test_main_custom_args_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "custom_ok"}
    
    custom_args = [
        "--conversation-id", "custom-conv-123",
        "--task-id", "T-custom-task-000",
        "--batch-id", "custom-batch-000",
        "--status", "passed",
        "--error-details", '{"info": "no_error"}',
        "--batch-summary", '{"passed": 1, "failed": 0, "skipped": 0, "total": 1}'
    ]
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi5.main(custom_args)
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("custom-conv-123")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-custom-task-000",
        "passed",
        {"info": "no_error"}
    )
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "custom-batch-000",
        {"passed": 1, "failed": 0, "skipped": 0, "total": 1}
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert '{"status": "custom_ok"}' in captured.out


@pytest.mark.parametrize(
    "invalid_arg_name, invalid_json_str",
    [
        ("--error-details", "invalid_json"),
        ("--batch-summary", "invalid_json"),
    ]
)
def test_main_invalid_json_args(capsys, invalid_arg_name, invalid_json_str):
    custom_args = [invalid_arg_name, invalid_json_str]
    
    with pytest.raises(SystemExit) as excinfo:
        mark_tasks_p27_multi5.main(custom_args)
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "JSON decode error occurred: Invalid JSON in" in captured.err


def test_main_debug_flag_on_exception(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Fatal execution error")
    
    custom_args = ["--debug"]
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main(custom_args)
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Value error occurred: Fatal execution error" in captured.err
    assert "Traceback (most recent call last):" in captured.err


def test_hub_report_error_exception_logged(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Process failed")
    mock_hub_instance.flash_report_error.side_effect = RuntimeError("Disk IO failed")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main([])
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Failed to report error to hub: Disk IO failed" in captured.err
    assert "Value error occurred: Process failed" in captured.err


def test_main_non_dict_json_error_details(capsys):
    with pytest.raises(SystemExit) as excinfo:
        mark_tasks_p27_multi5.main(["--error-details", "[1, 2]"])
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Value error occurred: --error-details must be a JSON object, got list" in captured.err


def test_main_non_dict_json_batch_summary(capsys):
    with pytest.raises(SystemExit) as excinfo:
        mark_tasks_p27_multi5.main(["--batch-summary", "123"])
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Value error occurred: --batch-summary must be a JSON object, got int" in captured.err


def test_main_opus_quota_exceeded_exception(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = OpusQuotaExceededException("Weekly quota exceeded")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi5.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_tasks_p27_multi5.main([])
                
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Opus quota exceeded error: Weekly quota exceeded" in captured.err
    mock_hub_instance.flash_report_error.assert_called_once_with(
        "OpusQuotaExceededException: Weekly quota exceeded", module="mark_tasks_p27_multi5"
    )


