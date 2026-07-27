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

from agents.orchestration.mark_tasks_p27_batch_4ab330 import (
    main,
    setup_orchestration_hub,
    extract_task_components,
    register_task_status,
    register_all_tasks_status,
    update_session_heartbeat,
    display_session_status,
    _get_exception_line,
    register_technical_debt
)

def test_setup_orchestration_hub():
    """setup_orchestration_hub() が正しく OrchestrationHub を初期化することを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub") as mock_hub_class:
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
    """main() 関数の実行と OrchestrationHub 連携 of the whole flow"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub") as mock_hub_class:
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
        
        module_name = "agents.orchestration.mark_tasks_p27_batch_4ab330"
        with patch.dict("sys.modules"):
            if module_name in sys.modules:
                del sys.modules[module_name]
            runpy.run_module(module_name, run_name="__main__")
        
        assert mock_hub.register_flash_conversation_id.call_count == 1

def test_setup_orchestration_hub_error():
    """setup_orchestration_hub が例外発生時に ValueError などを適切に raise することを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.register_flash_conversation_id.side_effect = ValueError("Invalid ID")
        with pytest.raises(ValueError, match="Invalid ID"):
            setup_orchestration_hub("invalid_conv_id")

def test_extract_task_components_error():
    """extract_task_components が KeyError 発生時に適切に raise することを確認"""
    invalid_task_info = {"status": "pass"}  # task_id と report が不足
    with pytest.raises(KeyError):
        extract_task_components(invalid_task_info)

def test_register_task_status_error():
    """register_task_status が例外発生時に適切に raise することを確認"""
    mock_hub = MagicMock()
    # mock_hub の動作でエラーを起こす
    mock_hub.mark_task_done.side_effect = RuntimeError("DB error")
    task_info = {
        "task_id": "T-test-task",
        "status": "pass",
        "report": {"message": "msg", "changed_files": []}
    }
    with pytest.raises(RuntimeError, match="DB error"):
        register_task_status(mock_hub, task_info)

def test_main_execution_error():
    """main が例外発生時に適切に SystemExit で終了することを確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.setup_orchestration_hub") as mock_setup:
        mock_setup.side_effect = RuntimeError("Connection failed")
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

# --- 新規追加のテスト ---

def test_get_exception_line():
    """_get_exception_line の挙動を確認"""
    # tb が None の場合
    assert _get_exception_line(None, 42) == 42
    
    # ダミーのトレースバックフレームをモックする (マッチする場合)
    mock_frame = MagicMock()
    mock_frame.filename = "mark_tasks_p27_batch_4ab330.py"
    mock_frame.lineno = 123
    
    with patch("traceback.extract_tb", return_value=[mock_frame]):
        mock_tb = MagicMock()
        line_no = _get_exception_line(mock_tb, 999)
        assert line_no == 123

def test_get_exception_line_no_match():
    """_get_exception_line で一致するファイルがなかった場合のフォールバックテスト"""
    mock_frame = MagicMock()
    mock_frame.filename = "some_other_file.py"
    mock_frame.lineno = 456
    
    with patch("traceback.extract_tb", return_value=[mock_frame]):
        mock_tb = MagicMock()
        line_no = _get_exception_line(mock_tb, 999)
        assert line_no == 999

def test_register_technical_debt():
    """register_technical_debt が技術負債を正しく登録することを確認"""
    mock_store = MagicMock()
    
    # 1. 通常のエラーは登録されること
    err = ValueError("value error")
    register_technical_debt(100, "pattern", "some notes", exception=err, _store=mock_store)
    mock_store.register_debt.assert_called_once_with(
        category="MINOR_INFRA",
        file_path="backend/agents/orchestration/mark_tasks_p27_batch_4ab330.py",
        line_number=100,
        pattern="pattern",
        cause_pattern="DP-01",
        fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
        registered_by="sprint_bug_hunter",
        notes="some notes",
        tags=["bug_hunter", "except_exception"]
    )
    
    # 2. インフラ・接続エラーは登録がスキップされること
    mock_store.reset_mock()
    infra_err = ConnectionError("conn error")
    register_technical_debt(100, "pattern", "some notes", exception=infra_err, _store=mock_store)
    mock_store.register_debt.assert_not_called()

def test_register_technical_debt_exception_handling():
    """register_technical_debt 内で例外が発生した際のフォールバックテスト"""
    mock_store = MagicMock()
    mock_store.register_debt.side_effect = Exception("Failed to save")
    
    # 例外が外に漏れずに正常に終了することを確認
    register_technical_debt(100, "pattern", "notes", exception=None, _store=mock_store)

def test_setup_orchestration_hub_unexpected_exception():
    """setup_orchestration_hub で想定外の例外が発生した際の挙動を確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.OrchestrationHub") as mock_hub_class:
        mock_hub_class.side_effect = Exception("Unexpected")
        
        # register_technical_debt 内の TechnicalDebtStore をモックする
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_tds_class:
            mock_store = mock_tds_class.return_value
            with pytest.raises(Exception, match="Unexpected"):
                setup_orchestration_hub("test_conv")
            mock_store.register_debt.assert_called_once()

def test_extract_task_components_unexpected_exception():
    """extract_task_components で想定外の例外が発生した際の挙動を確認"""
    class RogueDict(dict):
        def __getitem__(self, key):
            raise ValueError("Unexpected error for testing")
            
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_tds_class:
        mock_store = mock_tds_class.return_value
        with pytest.raises(Exception):
            extract_task_components(RogueDict())
        mock_store.register_debt.assert_called_once()

@patch("agents.orchestration.mark_tasks_p27_batch_4ab330.register_technical_debt")
def test_register_task_status_unexpected_exception(mock_register):
    """register_task_status で想定外の例外が発生した際の挙動を確認"""
    mock_hub = MagicMock()
    # mark_task_done で想定外の例外を起こす
    mock_hub.mark_task_done.side_effect = Exception("Unexpected db error")
    task_info = {
        "task_id": "T-test-task",
        "status": "pass",
        "report": {"message": "msg", "changed_files": []}
    }
    with pytest.raises(Exception, match="Unexpected db error"):
        register_task_status(mock_hub, task_info)
    mock_register.assert_called_once()

@patch("agents.orchestration.mark_tasks_p27_batch_4ab330.register_technical_debt")
def test_main_unexpected_exception(mock_register):
    """main で想定外の例外が発生した際の挙動を確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_4ab330.setup_orchestration_hub") as mock_setup:
        mock_setup.side_effect = Exception("Fatal unexpected error")
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        mock_register.assert_called_once()
