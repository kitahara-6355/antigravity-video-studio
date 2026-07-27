import sys
import os
import json
import runpy
from unittest.mock import MagicMock, patch
import pytest

# パスの追加
sys.path.insert(0, '.')
sys.path.insert(0, 'backend')

from backend.agents.orchestration.flash_runner_next_batch import (
    initialize_hub,
    execute_heartbeat,
    fetch_and_display_batch,
    display_status,
    main
)

def test_initialize_hub():
    """initialize_hubが正しくOrchestrationHubを初期化しIDを登録することを確認"""
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        hub = initialize_hub("test-conv-id")
        assert hub == mock_hub_instance
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("test-conv-id")


def test_execute_heartbeat():
    """execute_heartbeatがOrchestrationHubのflash_update_heartbeatを呼び出すことを確認"""
    mock_hub = MagicMock()
    execute_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()


def test_fetch_and_display_batch(capsys):
    """fetch_and_display_batchが標準出力にバッチ情報を表示し、結果を返すことを確認"""
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {"tasks": [{"id": 1}]}
    res = fetch_and_display_batch(mock_hub, phase=27, milestone="M27.1", batch_size=6)
    assert res == {"tasks": [{"id": 1}]}
    mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=6)
    
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert '"id": 1' in captured.out


def test_display_status(capsys):
    """display_statusがステータスをフォーマットして標準出力に表示することを確認"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "Status message"}
    display_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "=== STATUS ===" in captured.out
    assert "Status message" in captured.out


def test_main_success(capsys):
    """main関数の正常系フローのテスト"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {"tasks": []}
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Normal status"}
    
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()
        
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once()
    mock_hub_instance.generate_flash_status.assert_called_once()


def test_main_failure():
    """main関数で例外が発生した際のエラーログ記録と sys.exit(1) の検証"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = RuntimeError("Simulated failure")
    
    with patch("backend.agents.orchestration.flash_runner_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.flash_runner_next_batch.logger") as mock_logger, \
         pytest.raises(SystemExit) as exc_info:
        main()
        
    assert exc_info.value.code == 1
    mock_logger.exception.assert_called_once()
    assert "Error in flash_runner_next_batch execution" in mock_logger.exception.call_args[0][0]


def test_script_execution(capsys):
    """スクリプト直接実行時の __main__ ブロックの動作をテスト"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = []
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status output"}

    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        script_path = os.path.abspath("backend/agents/orchestration/flash_runner_next_batch.py")
        runpy.run_path(script_path, run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
