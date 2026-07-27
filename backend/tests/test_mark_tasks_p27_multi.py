import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_multi

def test_main_success(capsys):
    # OrchestrationHub をモック
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # 正常系メイン関数テスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi.main()
        
    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    # mark_task_done の2回呼び出しの検証
    assert mock_hub_instance.mark_task_done.call_count == 2
    
    # 1回目の呼び出し
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_214e16-thumbnail-001",
        "pass",
        {
            "message": "harness/evaluator_optimizer.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/harness/evaluator_optimizer.py",
                "tests/test_evaluator_optimizer.py"
            ]
        }
    )
    
    # 2回目の呼び出し
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_214e16-bug_hunter-000",
        "pass",
        {
            "message": "graded_previews/nhk_subtitle_scorer.py の例外処理保護とテスト追加。",
            "changed_files": [
                "backend/graded_previews/nhk_subtitle_scorer.py",
                "backend/tests/test_nhk_subtitle_scorer.py"
            ]
        }
    )
    
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "ok"}' in captured.out

def test_main_as_script(capsys):
    # スクリプトとして直接実行された場合のテスト (__name__ == "__main__")
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "script_ok"}
    
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    assert mock_hub_instance.mark_task_done.call_count == 2
    
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "script_ok"}' in captured.out

def test_main_hub_exception(capsys):
    # OrchestrationHubで例外が発生した場合に適切に例外が上に伝播することをテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Hub process error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(ValueError, match="Hub process error"):
                mark_tasks_p27_multi.main()
