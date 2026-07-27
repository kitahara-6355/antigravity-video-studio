import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# ルートパスを追加してインポート可能にする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import backend.agents.orchestration.flash_runner_next_batch as runner


def test_initialize_hub():
    """initialize_hub() が正しく OrchestrationHub を初期化し、IDを登録することを確認"""
    mock_hub = MagicMock()
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub):
        res = runner.initialize_hub("test-conv-id")
        assert res == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id")


def test_execute_heartbeat():
    """execute_heartbeat() が flash_update_heartbeat() を呼び出すことを確認"""
    mock_hub = MagicMock()
    runner.execute_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()


def test_fetch_and_display_batch():
    """fetch_and_display_batch() が get_next_batch() を呼び出し、結果を返すことを確認"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"batch_id": "b1"}
    res = runner.fetch_and_display_batch(mock_hub, phase=27, milestone="M27.1", batch_size=8)
    assert res == {"batch_id": "b1"}
    mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)


def test_display_status():
    """display_status() が generate_flash_status() を呼び出すことを確認"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "mock-status"}
    runner.display_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()


def test_runner_main_success():
    """runner.main() が正常に OrchestrationHub を呼び出し、必要なメソッドが実行されるかテスト"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"batch_id": "batch_abc", "tasks": []}
    mock_hub.generate_flash_status.return_value = {
        "formatted": "Mocked Status Output"
    }
    
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub):
        runner.main()
        
        # 各メソッドの呼び出し検証
        mock_hub.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)
        mock_hub.generate_flash_status.assert_called_once()


def test_runner_main_failure():
    """OrchestrationHub の処理中に例外が発生した場合、エラーがログ出力され sys.exit(1) で終了するかテスト"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.side_effect = Exception("Test connection error")
    
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub), \
         patch("backend.agents.orchestration.flash_runner_next_batch.logger") as mock_logger:
        
        with pytest.raises(SystemExit) as exc_info:
            runner.main()
            
        assert exc_info.value.code == 1
        mock_logger.exception.assert_called_once()
        args, kwargs = mock_logger.exception.call_args
        assert args[0] == "Error in flash_runner_next_batch execution: %s"
        assert isinstance(args[1], Exception)
        assert str(args[1]) == "Test connection error"


