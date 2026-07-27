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
    initialize_orchestration_hub,
    process_task_marking,
    finalize_hub_session,
    mark_single_task,
)

def test_main_execution():
    """main() 関数の実行と OrchestrationHub 連携の検証"""
    with patch("agents.orchestration.mark_tasks_p27_batch_d21647.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        main()
        
        # 会話ID of flash check
        mock_hub.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
        
        # 心拍更新とステータス表示の検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()
        
        # 各タスクのマーク状況を検証
        expected_calls = [
            ("T-batch_d21647-thumbnail-000", "pass"),
            ("T-batch_d21647-refactor-000", "pass"),
            ("T-batch_d21647-bug_hunter-000", "pass"),
            ("T-batch_d21647-test_weaver-000", "pass"),
            ("T-batch_d21647-test_weaver-001", "pass"),
            ("T-batch_d21647-thumbnail-001", "skip"),
        ]
        
        # 呼び出された回数の検証
        assert mock_hub.mark_task_done.call_count == len(expected_calls)
        
        # 各呼び出し引数の検証
        for i, (task_id, status) in enumerate(expected_calls):
            args, _ = mock_hub.mark_task_done.call_args_list[i]
            assert args[0] == task_id
            assert args[1] == status

def test_script_execution_via_runpy():
    """runpy を使用して __name__ == "__main__" として実行する"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        # スクリプトを __main__ として実行
        runpy.run_module("agents.orchestration.mark_tasks_p27_batch_d21647", run_name="__main__")
        
        assert mock_hub.register_flash_conversation_id.call_count == 1

def test_initialize_orchestration_hub():
    """initialize_orchestration_hub() が Hub を初期化し会話IDを正しく登録することを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_d21647.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        hub = initialize_orchestration_hub()
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")

def test_initialize_orchestration_hub_with_custom_id():
    """initialize_orchestration_hub() に任意の会話IDを渡せることを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_d21647.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        custom_id = "custom-conversation-id-12345"
        hub = initialize_orchestration_hub(custom_id)
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with(custom_id)

def test_process_task_marking():
    """process_task_marking() がすべてのタスクをマークすることを確認"""
    mock_hub = MagicMock()
    process_task_marking(mock_hub)
    
    expected_calls = [
        ("T-batch_d21647-thumbnail-000", "pass"),
        ("T-batch_d21647-refactor-000", "pass"),
        ("T-batch_d21647-bug_hunter-000", "pass"),
        ("T-batch_d21647-test_weaver-000", "pass"),
        ("T-batch_d21647-test_weaver-001", "pass"),
        ("T-batch_d21647-thumbnail-001", "skip"),
    ]
    
    assert mock_hub.mark_task_done.call_count == len(expected_calls)
    for i, (task_id, status) in enumerate(expected_calls):
        args, _ = mock_hub.mark_task_done.call_args_list[i]
        assert args[0] == task_id
        assert args[1] == status

def test_process_task_marking_with_custom_tasks():
    """process_task_marking() に任意のタスクリストを渡して処理できることを確認"""
    mock_hub = MagicMock()
    custom_tasks = [
        {
            "task_id": "T-custom-task-001",
            "status": "pass",
            "report": {"message": "done", "changed_files": []}
        },
        {
            "task_id": "T-custom-task-002",
            "status": "fail",
            "report": {"error": "error", "changed_files": []}
        }
    ]
    process_task_marking(mock_hub, custom_tasks)
    
    assert mock_hub.mark_task_done.call_count == len(custom_tasks)
    for i, task in enumerate(custom_tasks):
        args, _ = mock_hub.mark_task_done.call_args_list[i]
        assert args[0] == task["task_id"]
        assert args[1] == task["status"]

def test_finalize_hub_session():
    """finalize_hub_session() が心拍更新とステータス生成を行うことを確認"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
    finalize_hub_session(mock_hub)
    
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.generate_flash_status.assert_called_once()

def test_mark_single_task():
    """mark_single_task() が単一のタスクを正しくマークすることを確認"""
    mock_hub = MagicMock()
    task_info = {
        "task_id": "T-test-task-123",
        "status": "pass",
        "report": {"message": "test message", "changed_files": []}
    }
    
    mark_single_task(mock_hub, task_info)
    
    mock_hub.mark_task_done.assert_called_once_with(
        "T-test-task-123",
        "pass",
        {"message": "test message", "changed_files": []}
    )

