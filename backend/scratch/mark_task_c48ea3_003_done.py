import sys
from pathlib import Path
from typing import Any, Dict, Tuple
from backend.agents.orchestration import OrchestrationHub

# 定数の定義
TARGET_TASK_ID = "T-batch_c48ea3-thumbnail-003"
EXECUTION_RESULT = "pass"
REPORT_MESSAGE = "core/context.py: カバレッジ 100% 維持。エッジケース・異常系のテストケースを追加して堅牢性を向上"
CHANGED_FILES = ["backend/tests/test_context.py"]

def add_project_root_to_sys_path() -> None:
    """プロジェクトのルートディレクトリを sys.path に追加する"""
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

def get_thumbnail_task_details() -> Tuple[str, str, Dict[str, Any]]:
    """タスク報告に必要なタスクID、実行結果、レポート詳細を取得する"""
    report = {
        "message": REPORT_MESSAGE,
        "changed_files": CHANGED_FILES
    }
    return TARGET_TASK_ID, EXECUTION_RESULT, report

def report_thumbnail_task_completion(orchestration_hub: OrchestrationHub) -> None:
    """T-batch_c48ea3-thumbnail-003 タスクの完了を記録し、心拍を更新する"""
    orchestration_hub.flash_update_heartbeat()
    
    task_id, result, report = get_thumbnail_task_details()
    
    orchestration_hub.mark_task_done(
        task_id=task_id,
        result=result,
        report=report
    )

add_project_root_to_sys_path()
orchestration_hub = OrchestrationHub()
report_thumbnail_task_completion(orchestration_hub)
