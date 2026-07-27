import os
import sys
import traceback

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

_TASKS_TO_MARK = [
    {
        "task_id": "T-batch_f076d6-thumbnail-000",
        "result": "pass",
        "report": {
            "message": "plugins/opening_ending_plugin.py: カバレッジ 100% 維持。部分失敗の処理や境界値動作、モデル要件などの堅牢性テストを追加",
            "changed_files": ["backend/tests/test_shared/test_opening_ending_plugin.py"]
        }
    },
    {
        "task_id": "T-batch_f076d6-thumbnail-001",
        "result": "pass",
        "report": {
            "message": "core/context.py: カバレッジ 100% 維持。広張データのデフォルトアクセス、キー欠落時フォールバック等のテストを追加",
            "changed_files": ["backend/tests/test_context.py"]
        }
    }
]

def _send_heartbeat(hub: OrchestrationHub) -> None:
    """OrchestrationHub の心拍を更新する。"""
    hub.flash_update_heartbeat()

def _mark_single_task_completed(hub: OrchestrationHub, task: dict) -> None:
    """単一タスクの完了マークを記録する。"""
    hub.mark_task_done(
        task_id=task["task_id"],
        result=task["result"],
        report=task["report"]
    )

def mark_all_tasks_completed(hub: OrchestrationHub) -> None:
    """全タスクを完了としてマークする。"""
    _send_heartbeat(hub)
    for task in _TASKS_TO_MARK:
        _mark_single_task_completed(hub, task)

def log_debt_on_failure(error: Exception, fallback_line: int = 58) -> None:
    """スクリプト実行失敗時に技術負債を登録する。"""
    tb = traceback.extract_tb(sys.exc_info()[2])
    line_number = tb[-1].lineno if tb else fallback_line
    try:
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="scratch/mark_tasks_f076d6_000_001_done.py",
            line_number=line_number,
            pattern="except Exception as e:",
            registered_by="thumbnail_task",
            notes=f"Scratch script execution failure handler: {str(error)}"
        )
    except Exception as debt_store_error:
        print(f"Failed to register technical debt: {debt_store_error}", file=sys.stderr)

def main() -> int:
    try:
        hub = OrchestrationHub()
        mark_all_tasks_completed(hub)
        return 0
    except Exception as hub_error:
        log_debt_on_failure(hub_error, fallback_line=58)
        print(f"Error marking tasks as done: {hub_error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
