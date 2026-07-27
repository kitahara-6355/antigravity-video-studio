import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 1. T-batch_034cb4-bug_hunter-000 (scratch/get_next_batch.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-000", "pass", {
        "message": "scratch/get_next_batch.py の直接実行時の ModuleNotFoundError を sys.path 修正により解消。アサーション不整合の修正および直接実行テストを追加しました。",
        "changed_files": [
            "backend/scratch/get_next_batch.py",
            "tests/test_get_next_batch.py",
            "tests/test_scratch_get_next_batch.py"
        ]
    })
    print("Task 000 marked.")
    
    # 2. T-batch_034cb4-bug_hunter-001 (error_reporter.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-001", "pass", {
        "message": "error_reporter.py および FastAPI エンドポイントでの例外処理（500、503エラー）の堅牢化を行い、例外ハンドリング・再レイズのテストを追加しました。",
        "changed_files": [
            "backend/error_reporter.py",
            "backend/tests/test_shared/test_service_and_errors.py",
            "backend/agents/orchestration/flash_assign_subagents_8.py"
        ]
    })
    print("Task 001 marked.")
    
    # 3. T-batch_034cb4-bug_hunter-002 (plugins/report_generator_plugin.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-002", "pass", {
        "message": "report_generator_plugin.py で無効なデータ型や None に対する型チェックと安全なフォールバックを実装。フォールバック値アサーションのテストを追加しました。",
        "changed_files": [
            "backend/plugins/report_generator_plugin.py",
            "backend/tests/test_shared/test_report_generator_plugin_edge_cases.py"
        ]
    })
    print("Task 002 marked.")
    
    # 4. T-batch_034cb4-bug_hunter-003 (agents/director.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-003", "pass", {
        "message": "agent_base.py 内の WebSocket 例外ハンドラでの logger 未定義による NameError を解消。テストでフォールバックの正常動作を確認しました。",
        "changed_files": [
            "backend/agents/agent_base.py",
            "backend/tests/test_director.py"
        ]
    })
    print("Task 003 marked.")
    
    # 5. T-batch_034cb4-bug_hunter-004 (agents/orchestration/learning_integration.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-004", "pass", {
        "message": "task_learning_engine.py で _module_timeline 属性の未初期化による AttributeError を初期化追加で解消。データ空・正常系・例外発生のインテグレーションテストを追加しました。",
        "changed_files": [
            "backend/agents/orchestration/learning_integration.py",
            "backend/agents/orchestration/task_learning_engine.py",
            "backend/tests/test_learning_integration.py"
        ]
    })
    print("Task 004 marked.")
    
    # 6. T-batch_034cb4-bug_hunter-005 (service_container.py)
    hub.mark_task_done("T-batch_034cb4-bug_hunter-005", "pass", {
        "message": "service_container.py の依存関係ロード・心拍レジリエンス規約とのアサーション不整合を修正。インポートエラー時のフォールバックテストを追加しました。",
        "changed_files": [
            "backend/tests/test_flash_assign_subagents_8.py",
            "backend/tests/test_shared/test_service_and_errors.py"
        ]
    })
    print("Task 005 marked.")

if __name__ == "__main__":
    main()
