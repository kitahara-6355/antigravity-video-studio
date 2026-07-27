import sys
import os
import json
import runpy
from unittest.mock import MagicMock, patch
import pytest

# パスの追加
sys.path.insert(0, '.')
sys.path.insert(0, 'backend')

def test_main_function(capsys):
    """main関数がOrchestrationHubを正しく呼び出し、出力をフォーマットすることをテスト"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = [{"id": "task-1", "status": "pending"}]
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Flash status details here"}

    # インポート元である backend.agents.orchestration.OrchestrationHub 自体をパッチする
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        from backend.agents.orchestration.flash_runner_next_batch_7 import main
        main()

    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=6)
    mock_hub_instance.generate_flash_status.assert_called_once()

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert "task-1" in captured.out
    assert "=== STATUS ===" in captured.out
    assert "Flash status details here" in captured.out


def test_script_execution(capsys):
    """スクリプト直接実行時の __main__ ブロックの動作をテスト (runpyを使用)"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = []
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status output"}

    # インポート元である backend.agents.orchestration.OrchestrationHub 自体をパッチする
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        script_path = os.path.abspath("backend/agents/orchestration/flash_runner_next_batch_7.py")
        runpy.run_path(script_path, run_name="__main__")

    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "=== BATCH_TASKS ===" in captured.out
    assert "=== STATUS ===" in captured.out
