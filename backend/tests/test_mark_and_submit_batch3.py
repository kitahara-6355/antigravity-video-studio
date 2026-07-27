import sys
import os
import json
from unittest.mock import MagicMock, patch
import pytest

# 動的にプロジェクトルートを sys.path の先頭に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_mark_and_submit_batch3_main_success(capsys):
    import runpy
    if "backend.agents.orchestration.mark_and_submit_batch3" in sys.modules:
        del sys.modules["backend.agents.orchestration.mark_and_submit_batch3"]

    mock_hub = MagicMock()
    dummy_status = {"status": "running", "progress": 0.5}
    mock_hub.generate_flash_status.return_value = dummy_status

    original_path = sys.path.copy()
    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            # runpy.run_module を使用して __name__ == "__main__" ブロックを正しくモジュールカバレッジに含める
            runpy.run_module("backend.agents.orchestration.mark_and_submit_batch3", run_name="__main__")
    finally:
        sys.path = original_path

    mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_a97ee3-thumbnail-001",
        "pass",
        {
            "message": "agents/workers/proofread_worker.py & routers/preview.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/agents/workers/proofread_worker.py",
                "backend/routers/preview.py",
                "backend/tests/test_thumbnail_quality_extra.py"
            ]
        }
    )
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_a97ee3",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS:" in captured.out


def test_generate_task_summary_top20_with_string_result(tmp_path):
    """
    generate_subagent_reports.py 内の generate_task_summary_top20() において、
    task の result が辞書ではなく文字列の場合でも、AttributeError にならず
    正常に処理されるか（バグ修正の確認）をテストする。
    """
    from backend.agents.orchestration import generate_subagent_reports
    from datetime import datetime, timezone
    
    # テスト用のダミーの reports.jsonl ファイルを作成
    dummy_reports_path = tmp_path / "flash_reports.jsonl"
    now_str = datetime.now(timezone.utc).isoformat()
    dummy_entry = {
        "timestamp": now_str,
        "phase": 27,
        "milestone": "M27.1",
        "batch_id": "batch_test",
        "tasks": [
            {
                "id": "T-batch_test-thumbnail-000",
                "group": "thumbnail",
                "target_module": "dummy_module.py",
                "status": "pass",
                "result": "passed",  # 文字列型 (以前はここで AttributeError)
                "started_at": now_str,
                "completed_at": now_str
            }
        ]
    }
    
    with open(dummy_reports_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(dummy_entry) + "\n")
        
    with patch("backend.agents.orchestration.generate_subagent_reports.FLASH_REPORTS_PATH", str(dummy_reports_path)):
        # エラーが発生せずに、Markdownレポートが生成されること
        md = generate_subagent_reports.generate_task_summary_top20()
        assert md != ""
        assert "Dummy Module" in md or "dummy_module" in md or "一般処理" in md or "その他" in md
