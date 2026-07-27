import sys
import json
import pytest
import runpy
import warnings
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_multi7

def test_mark_thumbnail_tasks_as_failed():
    mock_hub = MagicMock()
    mark_tasks_p27_multi7.mark_thumbnail_tasks_as_failed(mock_hub)
    
    # 期待されるタスクIDの検証
    assert mock_hub.mark_task_done.call_count == 2
    mock_hub.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-000", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-001", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})

def test_report_batch_failure(capsys):
    mock_hub = MagicMock()
    mark_tasks_p27_multi7.report_batch_failure(mock_hub)
    
    mock_hub.submit_batch_report.assert_called_once_with(
        mark_tasks_p27_multi7.BATCH_ID,
        {
            "passed": 0,
            "failed": 2,
            "skipped": 0,
            "total": 2,
        }
    )
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out

def test_display_latest_status(capsys):
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "mock_status_formatted_string"}
    
    mark_tasks_p27_multi7.display_latest_status(mock_hub)
    
    mock_hub.generate_flash_status.assert_called_once()
    captured = capsys.readouterr()
    assert "=== STATUS ===" in captured.out
    assert "mock_status_formatted_string" in captured.out

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "success_formatted_string"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi7.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with(mark_tasks_p27_multi7.CONVERSATION_ID)
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-000", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub_instance.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-001", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        mark_tasks_p27_multi7.BATCH_ID,
        {"passed": 0, "failed": 2, "skipped": 0, "total": 2}
    )
    mock_hub_instance.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "success_formatted_string" in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "script_formatted_string"}
    
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi7.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with(mark_tasks_p27_multi7.CONVERSATION_ID)
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-000", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub_instance.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-001", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        mark_tasks_p27_multi7.BATCH_ID,
        {"passed": 0, "failed": 2, "skipped": 0, "total": 2}
    )
    mock_hub_instance.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "script_formatted_string" in captured.out

def test_main_hub_exception():
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Hub process error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(ValueError, match="Hub process error"):
                mark_tasks_p27_multi7.main()

def test_main_direct_execution_with_hub_failure():
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = Exception("Failed to update heartbeat")
    
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi7.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(Exception, match="Failed to update heartbeat"):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    runpy.run_path(script_path, run_name="__main__")

def test_mark_thumbnail_tasks_as_failed_partial_failure():
    """片方のタスク更新でエラーが発生しても、もう片方のタスク更新が試みられること、および例外が再送出されることの検証"""
    mock_hub = MagicMock()
    # 000 で ValueError を投げ、001 では成功させる
    mock_hub.mark_task_done.side_effect = [ValueError("Simulated error for 000"), None]
    
    with pytest.raises(ValueError, match="Simulated error for 000"):
        mark_tasks_p27_multi7.mark_thumbnail_tasks_as_failed(mock_hub)
        
    # 2回呼び出されたことの検証
    assert mock_hub.mark_task_done.call_count == 2
    mock_hub.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-000", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})
    mock_hub.mark_task_done.assert_any_call("T-batch_c4f4d2-thumbnail-001", "fail", {"error": mark_tasks_p27_multi7.ERROR_MESSAGE})

def test_display_latest_status_failure_not_raising():
    """最新ステータス表示で例外が発生しても、例外は再送出されず処理が終了することの検証"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = RuntimeError("Status generation failed")
    
    # 実行して例外が起きないことを確認
    mark_tasks_p27_multi7.display_latest_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()

def test_main_register_id_failure_raises():
    """会話ID登録失敗時に例外が適切に再送出されることの検証"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = RuntimeError("Registration failed")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(RuntimeError, match="Registration failed"):
                mark_tasks_p27_multi7.main()

def test_main_batch_report_failure_raises():
    """バッチ報告失敗時に例外が適切に再送出されることの検証"""
    mock_hub_instance = MagicMock()
    mock_hub_instance.submit_batch_report.side_effect = RuntimeError("Batch submission failed")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(RuntimeError, match="Batch submission failed"):
                mark_tasks_p27_multi7.main()


def test_main_orchestration_hub_init_failure():
    """OrchestrationHubの初期化失敗時に例外が適切に再送出されることの検証"""
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", side_effect=RuntimeError("Hub init failed")):
        with pytest.raises(RuntimeError, match="Hub init failed"):
            mark_tasks_p27_multi7.main()


def test_main_thumbnail_marking_failure():
    """サムネイルタスクのマーク失敗時に例外が適切に再送出されることの検証"""
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.mark_tasks_p27_multi7.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.mark_tasks_p27_multi7.mark_thumbnail_tasks_as_failed", side_effect=RuntimeError("Marking failed")):
            with pytest.raises(RuntimeError, match="Marking failed"):
                mark_tasks_p27_multi7.main()


def test_sys_path_insertion_coverage():
    """sys.pathにbackend_dirが含まれていない場合にsys.pathに追加されることの検証"""
    import importlib
    import os
    import sys
    
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(mark_tasks_p27_multi7.__file__), '..', '..'))
    
    # sys.path から一時的に削除
    original_path = sys.path.copy()
    try:
        while backend_dir in sys.path:
            sys.path.remove(backend_dir)
        
        # モジュールを再ロードして 9 行目を実行させる
        importlib.reload(mark_tasks_p27_multi7)
        
        # sys.path に backend_dir が追加されたことを確認
        assert backend_dir in sys.path
    finally:
        sys.path = original_path

