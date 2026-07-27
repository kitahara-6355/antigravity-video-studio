import sys
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_multi14

def test_main(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {
        "formatted": "mock_status_string"
    }

    # Patch import destination for test_main
    with patch("backend.agents.orchestration.mark_tasks_p27_multi14.OrchestrationHub", return_value=mock_hub_instance):
        mark_tasks_p27_multi14.main()

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    assert mock_hub_instance.flash_update_heartbeat.call_count == 2
    
    assert mock_hub_instance.mark_task_done.call_count == 2
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_ac027b-ds-ds-025",
        "pass",
        {
            "message": "バッチ batch_b5de01 でのタイムアウト失敗原因（ハング）に対し、subprocess.Popenモック安全規約および心拍レジリエンス規約、タイムアウト処理の改善（OrchestrationHubによる600秒タスクkillとタイムアウト復旧）が適用済みであることを確認し、対策完了と判定。",
            "changed_files": []
        }
    )
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_ac027b-test_weaver-000",
        "pass",
        {
            "message": "test_youtube_optimizer_router.py において routers/youtube_optimizer.py に対する 125 件のテストが 100% PASS し、カバレッジも 99% 達成していることを確認。",
            "changed_files": [
                "backend/tests/test_youtube_optimizer_router.py"
            ]
        }
    )

    mock_hub_instance.submit_batch_report.assert_called_once_with("batch_ac027b", {
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "total": 2,
    })

    mock_hub_instance.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS:" in captured.out

def test_main_as_script():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {
        "formatted": "mock_status_string"
    }

    # Patch import source for runpy execution
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        runpy.run_module("backend.agents.orchestration.mark_tasks_p27_multi14", run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once()
    assert mock_hub_instance.flash_update_heartbeat.call_count == 2
    mock_hub_instance.submit_batch_report.assert_called_once()
