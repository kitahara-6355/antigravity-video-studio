import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_multi9

def test_main_success(capsys):
    # OrchestrationHub をモック化
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "ok"}
    
    # 正常系メイン関数テスト
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi9.main()
        
    # メソッド呼び出しの検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    # 6個のタスクが skip としてマークされたことを検証
    expected_tasks = [
        "T-batch_6ff381-thumbnail-000",
        "T-batch_6ff381-thumbnail-001",
        "T-batch_6ff381-test_weaver-000",
        "T-batch_6ff381-test_weaver-001",
        "T-batch_6ff381-bug_hunter-000",
        "T-batch_6ff381-refactor-000"
    ]
    assert mock_hub_instance.mark_task_done.call_count == len(expected_tasks)
    
    for task_id in expected_tasks:
        mock_hub_instance.mark_task_done.assert_any_call(
            task_id,
            "skip",
            {
                "error": "SUBAGENT_TIMEOUT: 600秒以内に完了せず自動スキップ",
                "changed_files": []
            }
        )
        
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_6ff381",
        {
            "passed": 0,
            "failed": 0,
            "skipped": 6,
            "total": 6,
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "Heartbeat updated." in captured.out
    assert "Marked T-batch_6ff381-thumbnail-000 as skip." in captured.out
    assert "Batch report submitted." in captured.out
    assert "=== STATUS ===" in captured.out
    assert "ok" in captured.out

def test_main_as_script(capsys):
    # スクリプトとして直接実行された場合のテスト (__name__ == "__main__")
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "script_ok"}
    
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi9.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    expected_tasks = [
        "T-batch_6ff381-thumbnail-000",
        "T-batch_6ff381-thumbnail-001",
        "T-batch_6ff381-test_weaver-000",
        "T-batch_6ff381-test_weaver-001",
        "T-batch_6ff381-bug_hunter-000",
        "T-batch_6ff381-refactor-000"
    ]
    assert mock_hub_instance.mark_task_done.call_count == len(expected_tasks)
    
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_6ff381",
        {
            "passed": 0,
            "failed": 0,
            "skipped": 6,
            "total": 6,
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Heartbeat updated." in captured.out
    assert "Batch report submitted." in captured.out
    assert "script_ok" in captured.out

def test_main_hub_exception(capsys):
    # OrchestrationHubで例外が発生した場合に適切に例外が上に伝播することをテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = OSError("Hub process error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(OSError, match="Hub process error"):
                mark_tasks_p27_multi9.main()


def test_main_partial_task_failure(capsys):
    # 個別タスクマーク時に一部が例外を投げても、他のタスクが処理され、最後に例外が伝播すること
    mock_hub_instance = MagicMock()
    
    # 2番目のタスクのみ失敗するように side_effect を設定
    def side_effect_mark(task_id, status, payload):
        if task_id == "T-batch_6ff381-thumbnail-001":
            raise TimeoutError("Mark failed for thumbnail-001")
        return None
        
    mock_hub_instance.mark_task_done.side_effect = side_effect_mark
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "partial_ok"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(TimeoutError, match="Mark failed for thumbnail-001"):
                mark_tasks_p27_multi9.main()
                
    # すべてのタスクに対して呼び出しが試みられたことを検証 (call_count == 6)
    assert mock_hub_instance.mark_task_done.call_count == 6
    # バッチ完了報告も送信されていることを検証
    mock_hub_instance.submit_batch_report.assert_called_once()

def test_main_register_id_failure(capsys):
    # register_flash_conversation_idが失敗したとき、即座に終了して後続処理が行われないこと
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = OSError("Register ID error")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(OSError, match="Register ID error"):
                mark_tasks_p27_multi9.main()
                
    # 心拍更新やタスクマーク、バッチ報告は呼ばれない
    mock_hub_instance.flash_update_heartbeat.assert_not_called()
    mock_hub_instance.mark_task_done.assert_not_called()
    mock_hub_instance.submit_batch_report.assert_not_called()

def test_main_json_decode_error(capsys):
    # OrchestrationHub初期化時のJSONDecodeErrorが伝播することをテスト
    import json
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", side_effect=json.JSONDecodeError("Expecting value", "", 0)):
        with pytest.raises(json.JSONDecodeError, match="Expecting value"):
            mark_tasks_p27_multi9.main()

def test_main_subprocess_error(capsys):
    # submit_batch_report時のSubprocessErrorが伝播することをテスト
    import subprocess
    mock_hub_instance = MagicMock()
    mock_hub_instance.submit_batch_report.side_effect = subprocess.SubprocessError("Subprocess failed")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi9.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(subprocess.SubprocessError, match="Subprocess failed"):
                mark_tasks_p27_multi9.main()
