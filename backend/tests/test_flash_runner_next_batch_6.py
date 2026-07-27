import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# ルートパスを追加してインポート可能にする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import backend.agents.orchestration.flash_runner_next_batch_6 as runner

def test_initialize_hub_with_conversation():
    """initialize_hub_with_conversation が正常にOrchestrationHubを初期化し設定するかテスト"""
    mock_hub = MagicMock()
    with patch("backend.agents.orchestration.flash_runner_next_batch_6.OrchestrationHub", return_value=mock_hub):
        hub = runner.initialize_hub_with_conversation("test-conv-id")
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id")
        mock_hub.flash_update_heartbeat.assert_called_once()

def test_fetch_and_display_next_batch():
    """fetch_and_display_next_batch が正しくバッチを取得し出力するかテスト"""
    mock_hub = MagicMock()
    mock_batch = [{"id": "task-1"}]
    mock_hub.get_next_batch.return_value = mock_batch
    
    batch = runner.fetch_and_display_next_batch(mock_hub, phase=27, milestone="M27.1", batch_size=8)
    assert batch == mock_batch
    mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)

def test_display_current_status():
    """display_current_status が正しくステータスを出力するかテスト"""
    mock_hub = MagicMock()
    mock_status = {"formatted": "Status Info"}
    mock_hub.generate_flash_status.return_value = mock_status
    
    status = runner.display_current_status(mock_hub)
    assert status == mock_status
    mock_hub.generate_flash_status.assert_called_once()

def test_runner_main_success():
    """runner.main() が正常に動作することを確認"""
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.flash_runner_next_batch_6.initialize_hub_with_conversation", return_value=mock_hub) as mock_init, \
         patch("backend.agents.orchestration.flash_runner_next_batch_6.fetch_and_display_next_batch") as mock_fetch, \
         patch("backend.agents.orchestration.flash_runner_next_batch_6.display_current_status") as mock_display:
         
        runner.main()
        mock_init.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
        mock_fetch.assert_called_once_with(mock_hub, phase=27, milestone="M27.1", batch_size=8)
        mock_display.assert_called_once_with(mock_hub)

def test_runner_main_exception():
    """例外発生時に sys.exit(1) で終了し、ログが出力されることをテスト"""
    with patch("backend.agents.orchestration.flash_runner_next_batch_6.initialize_hub_with_conversation", side_effect=Exception("Connection error")), \
         patch("backend.agents.orchestration.flash_runner_next_batch_6.logger") as mock_logger:
         
        with pytest.raises(SystemExit) as exc_info:
            runner.main()
            
        assert exc_info.value.code == 1
        mock_logger.error.assert_called_once_with("Error in flash_runner_next_batch_6: Connection error")

