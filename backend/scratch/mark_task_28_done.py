import os
import sys

def setup_project_path() -> None:
    """プロジェクトルートディレクトリを sys.path に動的に追加します。"""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

setup_project_path()

from backend.agents.orchestration import OrchestrationHub

def mark_task_28_completed() -> None:
    """タスク T-batch_769699-thumbnail-028 を完了状態（pass）にします。"""
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    hub.mark_task_done(
        task_id="T-batch_769699-thumbnail-028",
        result="pass",
        report={
            "message": "routers/segments.py: カバレッジ 100% 達成。export_subtitles エンドポイントの422エラーバグを修正し、テストを実装",
            "changed_files": ["backend/routers/segments.py", "backend/tests/test_routers_segments.py"]
        }
    )

if __name__ == "__main__":
    mark_task_28_completed()
