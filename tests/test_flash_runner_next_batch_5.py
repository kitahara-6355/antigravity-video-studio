import sys
import os
import json
import runpy
from unittest.mock import MagicMock, patch
import pytest

# パスの追加
sys.path.insert(0, '.')
sys.path.insert(0, 'backend')

from backend.agents.orchestration.flash_runner_next_batch_5 import (
    init_orchestration_hub,
    update_heartbeat,
    fetch_next_batch,
    print_batch_tasks,
    get_flash_status,
    print_flash_status,
    main,
    format_batch_tasks,
    format_flash_status,
    run_flash_sequence,
    _is_config_or_runtime_error,
    execute_flash_sequence,
    display_flash_results
)

def test_init_orchestration_hub():
    """init_orchestration_hubが正しくOrchestrationHubを初期化しIDを登録することを確認"""
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub_instance):
        hub = init_orchestration_hub("test-conv-id")
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("test-conv-id")


def test_update_heartbeat():
    """update_heartbeatがOrchestrationHub the flash_update_heartbeatを呼び出すことを確認"""
    mock_hub = MagicMock()
    update_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()


def test_fetch_next_batch():
    """fetch_next_batchがOrchestrationHubのget_next_batchを呼び出すことを確認"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"tasks": []}
    res = fetch_next_batch(mock_hub, phase=27, milestone="M27.1", batch_size=8)
    assert res == {"tasks": []}
    mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)


def test_print_batch_tasks(capsys):
    """print_batch_tasksが期待される形式で出力することを確認"""
    batch_data = {"key": "val"}
    print_batch_tasks(batch_data)
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert '"key": "val"' in captured.out


def test_get_flash_status():
    """get_flash_statusがOrchestrationHubのgenerate_flash_statusを呼び出すことを確認"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "status_details"}
    res = get_flash_status(mock_hub)
    assert res == {"formatted": "status_details"}
    mock_hub.generate_flash_status.assert_called_once()


def test_print_flash_status(capsys):
    """print_flash_statusが期待される形式で出力することを確認"""
    status_data = {"formatted": "status_message"}
    print_flash_status(status_data)
    captured = capsys.readouterr()
    assert "=== STATUS ===" in captured.out
    assert "status_message" in captured.out


def test_main_function(capsys):
    """main関数がOrchestrationHubを正しく呼び出し、出力をフォーマットすることをテスト"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = [{"id": "task-5", "status": "pending"}]
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Flash status 5 details"}

    # flash_runner_next_batch_5 内の OrchestrationHub をパッチする
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub_instance):
        main()

    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)
    mock_hub_instance.generate_flash_status.assert_called_once()

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert "task-5" in captured.out
    assert "=== STATUS ===" in captured.out
    assert "Flash status 5 details" in captured.out


def test_main_function_exception():
    """main関数内で例外が発生した際、正しくエラーログを記録してsys.exit(1)することを確認"""
    mock_hub_instance = MagicMock()
    # 例外を発生させる
    mock_hub_instance.register_flash_conversation_id.side_effect = RuntimeError("Simulated failure")

    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.flash_runner_next_batch_5.logger") as mock_logger, \
         pytest.raises(SystemExit) as exc_info:
        main()

    # sys.exit(1) が呼ばれたことを確認
    assert exc_info.value.code == 1
    # ログが記録されたことを確認
    mock_logger.error.assert_called_once()
    assert "Error in flash_runner_next_batch_5:" in mock_logger.error.call_args[0][0]


def test_script_execution(capsys):
    """スクリプト直接実行時の __main__ ブロックの動作をテスト (runpyを使用)"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = []
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status output 5"}

    # runpy経由での実行時はインポート元の OrchestrationHub 自体をパッチする
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        script_path = os.path.abspath("backend/agents/orchestration/flash_runner_next_batch_5.py")
        runpy.run_path(script_path, run_name="__main__")

    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert "=== STATUS ===" in captured.out

def test_format_batch_tasks():
    """format_batch_tasksが期待される文字列フォーマットを生成することを確認"""
    batch_data = {"test_key": "test_val"}
    res = format_batch_tasks(batch_data)
    assert "=== BATCH_TASKS ===" in res
    assert '"test_key": "test_val"' in res
    assert "===================" in res

def test_format_flash_status():
    """format_flash_statusが期待される文字列フォーマットを生成することを確認"""
    status_data = {"formatted": "Flash status message"}
    res = format_flash_status(status_data)
    assert "=== STATUS ===" in res
    assert "Flash status message" in res
    assert "==============" in res

def test_run_flash_sequence():
    """run_flash_sequenceが順次必要なメソッドを呼び出すことを確認"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"tasks": []}
    mock_hub.generate_flash_status.return_value = {"formatted": "Status output"}
    
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.print_batch_tasks") as mock_print_batch, \
          patch("backend.agents.orchestration.flash_runner_next_batch_5.print_flash_status") as mock_print_status:
        run_flash_sequence(mock_hub)
        
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.get_next_batch.assert_called_once()
    mock_print_batch.assert_called_once_with({"tasks": []})
    mock_hub.generate_flash_status.assert_called_once()
    mock_print_status.assert_called_once_with({"formatted": "Status output"})

def test_main_function_value_error_exception():
    """main関数内でValueErrorが発生した際、正しくエラーログを記録してsys.exit(1)することを確認"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = ValueError("Simulated ValueError")

    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.flash_runner_next_batch_5.logger") as mock_logger, \
         pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_logger.error.assert_called_once()
    assert "Error in flash_runner_next_batch_5: Configuration or runtime error: Simulated ValueError" in mock_logger.error.call_args[0][0]

def test_main_function_unexpected_exception():
    """main関数内で一般的な例外が発生した際、正しくエラーログを記録してsys.exit(1)することを確認"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = Exception("Simulated unexpected Exception")

    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.flash_runner_next_batch_5.logger") as mock_logger, \
         pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_logger.error.assert_called_once()
    assert "Error in flash_runner_next_batch_5: Unexpected error: Simulated unexpected Exception" in mock_logger.error.call_args[0][0]

def test_is_config_or_runtime_error():
    """_is_config_or_runtime_errorが期待される例外型を正しく判別することを確認"""
    assert _is_config_or_runtime_error(ValueError("test")) is True
    assert _is_config_or_runtime_error(KeyError("test")) is True
    assert _is_config_or_runtime_error(RuntimeError("test")) is True
    assert _is_config_or_runtime_error(json.JSONDecodeError("test", "", 0)) is True
    assert _is_config_or_runtime_error(OSError("test")) is True
    assert _is_config_or_runtime_error(Exception("test")) is False


def test_execute_flash_sequence():
    """execute_flash_sequenceが心拍更新、バッチ取得、ステータス取得を順に呼び出すことを確認"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"tasks": []}
    mock_hub.generate_flash_status.return_value = {"formatted": "Status output"}
    
    batch, status = execute_flash_sequence(mock_hub)
    
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.get_next_batch.assert_called_once()
    mock_hub.generate_flash_status.assert_called_once()
    assert batch == {"tasks": []}
    assert status == {"formatted": "Status output"}


def test_display_flash_results():
    """display_flash_resultsが適切なprint関数群を呼び出すことを確認"""
    batch_data = {"key": "val"}
    status_data = {"formatted": "status_details"}
    
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.print_batch_tasks") as mock_print_batch, \
         patch("backend.agents.orchestration.flash_runner_next_batch_5.print_flash_status") as mock_print_status:
        display_flash_results(batch_data, status_data)
        mock_print_batch.assert_called_once_with(batch_data)
        mock_print_status.assert_called_once_with(status_data)


