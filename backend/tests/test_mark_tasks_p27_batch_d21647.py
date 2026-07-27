# -*- coding: utf-8 -*-
import sys
import os
import runpy
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_batch_d21647 import (
    main,
    setup_orchestration_hub,
    extract_task_components,
    register_task_status,
    register_all_tasks_status,
    update_session_heartbeat,
    display_session_status
)

def test_setup_orchestration_hub():
    """setup_orchestration_hub() が正しく OrchestrationHub を初期化することを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_d21647.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        hub = setup_orchestration_hub("test_conv_id")
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with("test_conv_id")

def test_extract_task_components():
    """extract_task_components() がタスク情報辞書から正しく要素を抽出することを確認"""
    task_info = {
        "task_id": "T-test",
        "status": "pass",
        "report": {"message": "hello", "changed_files": []}
    }
    task_id, status, report = extract_task_components(task_info)
    assert task_id == "T-test"
    assert status == "pass"
    assert report == {"message": "hello", "changed_files": []}

def test_register_task_status():
    """register_task_status() が単一のタスクを正しく登録することを確認"""
    mock_hub = MagicMock()
    task_info = {
        "task_id": "T-test-task",
        "status": "pass",
        "report": {"message": "msg", "changed_files": []}
    }
    register_task_status(mock_hub, task_info)
    mock_hub.mark_task_done.assert_called_once_with(
        "T-test-task", "pass", {"message": "msg", "changed_files": []}
    )

def test_register_all_tasks_status():
    """register_all_tasks_status() がリスト内の全タスクを登録することを確認"""
    mock_hub = MagicMock()
    task_list = [
        {"task_id": "T-1", "status": "pass", "report": {"message": "m1"}},
        {"task_id": "T-2", "status": "skip", "report": {"message": "m2"}},
    ]
    register_all_tasks_status(mock_hub, task_list)
    assert mock_hub.mark_task_done.call_count == 2
    mock_hub.mark_task_done.assert_any_call("T-1", "pass", {"message": "m1"})
    mock_hub.mark_task_done.assert_any_call("T-2", "skip", {"message": "m2"})

def test_update_session_heartbeat():
    """update_session_heartbeat() が心拍を更新することを確認"""
    mock_hub = MagicMock()
    update_session_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()

def test_display_session_status():
    """display_session_status() がステータスを生成して表示することを確認"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "Status display"}
    display_session_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()

def test_main_execution():
    """main() 関数の実行と OrchestrationHub 連携の全体フローの検証"""
    with patch("agents.orchestration.mark_tasks_p27_batch_d21647.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        main()
        
        # 会話IDの登録チェック
        mock_hub.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
        
        # 心拍更新とステータス表示の検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()
        
        # タスクマーク数検証
        assert mock_hub.mark_task_done.call_count == 6

def test_script_execution_via_runpy():
    """runpy を使用して __name__ == "__main__" として実行する"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        runpy.run_module("agents.orchestration.mark_tasks_p27_batch_d21647", run_name="__main__")
        
        assert mock_hub.register_flash_conversation_id.call_count == 1
