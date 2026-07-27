# -*- coding: utf-8 -*-
import sys
import os
import runpy
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_batch_712457 import (
    main,
    initialize_orchestration_hub,
    process_task_marking,
    finalize_hub_session,
    mark_single_task,
    FLASH_CONVERSATION_ID,
    BATCH_TASKS,
)

def test_main_execution():
    """main() 関数の実行と OrchestrationHub 連携の検証"""
    with patch("agents.orchestration.mark_tasks_p27_batch_712457.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        main()
        
        mock_hub.register_flash_conversation_id.assert_called_once_with("0c00ce38-f479-4e0c-853e-22aa566d725e")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()
        
        # 登録タスク数の検証
        assert mock_hub.mark_task_done.call_count == len(BATCH_TASKS)

def test_main_validation_error(capsys):
    """main() 実行時にバリデーションエラーが発生した場合のハンドリング検証と stderr 出力の確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_712457.initialize_orchestration_hub", side_effect=ValueError("Invalid ID")):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Validation error during orchestration marking: Invalid ID" in captured.err

def test_main_unexpected_error(capsys):
    """main() 実行時に予期せぬエラーが発生した場合の再スロー検証と stderr 出力の確認"""
    with patch("agents.orchestration.mark_tasks_p27_batch_712457.initialize_orchestration_hub", side_effect=RuntimeError("Fatal")):
        with pytest.raises(RuntimeError) as excinfo:
            main()
        assert str(excinfo.value) == "Fatal"
        captured = capsys.readouterr()
        assert "Unexpected error during orchestration marking: Fatal" in captured.err

def test_script_execution_via_runpy():
    """runpy を使用して __name__ == "__main__" として実行する"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.generate_flash_status.return_value = {"status": "success", "formatted": "Mock formatted status"}
        
        script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_712457.py")
        runpy.run_path(script_path, run_name="__main__")
        assert mock_hub.register_flash_conversation_id.call_count == 1

def test_initialize_orchestration_hub():
    """initialize_orchestration_hub() の初期化検証"""
    with patch("agents.orchestration.mark_tasks_p27_batch_712457.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        hub = initialize_orchestration_hub()
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with(FLASH_CONVERSATION_ID)

def test_initialize_orchestration_hub_invalid():
    """引数エラー検証"""
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        initialize_orchestration_hub(None)
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        initialize_orchestration_hub("")
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        initialize_orchestration_hub(12345)

def test_mark_single_task_invalid():
    """mark_single_task() の異常系入力型検証"""
    mock_hub = MagicMock()
    with pytest.raises(TypeError, match="task_info must be a dictionary"):
        mark_single_task(mock_hub, "not-a-dict")
        
    with pytest.raises(KeyError, match="task_info missing required keys"):
        mark_single_task(mock_hub, {"task_id": "T-1"})
        
    with pytest.raises(TypeError, match="Invalid data types in task_info values"):
        mark_single_task(mock_hub, {
            "task_id": 123,
            "status": "pass",
            "report": {}
        })

    with pytest.raises(TypeError, match="Invalid data types in task_info values"):
        mark_single_task(mock_hub, {
            "task_id": "T-1",
            "status": 123,
            "report": {}
        })

    with pytest.raises(TypeError, match="Invalid data types in task_info values"):
        mark_single_task(mock_hub, {
            "task_id": "T-1",
            "status": "pass",
            "report": "not-a-dict"
        })

def test_process_task_marking_invalid():
    """process_task_marking() の異常系入力型検証"""
    mock_hub = MagicMock()
    with pytest.raises(TypeError, match="tasks must be a list"):
        process_task_marking(mock_hub, "not-a-list")

def test_finalize_hub_session():
    """finalize_hub_session() が心拍更新とステータス表示を行うことを検証"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}
    status = finalize_hub_session(mock_hub)
    assert status == {"status": "ok"}
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.generate_flash_status.assert_called_once()
