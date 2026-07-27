import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    # 1. Mark test_weaver-000
    task_id_weaver0 = "T-batch_bfd6c5-test_weaver-000"
    report_weaver0 = {
        "message": "scratch/check_worktree_git.py において、環境変数付きデフォルトワークツリー確認テストおよびインポート時のフォールバック処理の模擬テストを追加し、カバレッジ100%を達成・全17テストPASSを確認しました。",
        "changed_files": [
            "backend/tests/test_scratch_check_worktree_git.py"
        ]
    }
    print(f"Marking task {task_id_weaver0} as pass...")
    hub.mark_task_done(task_id_weaver0, "pass", report_weaver0)

    # 2. Mark test_weaver-001
    task_id_weaver1 = "T-batch_bfd6c5-test_weaver-001"
    report_weaver1 = {
        "message": "main.py において、setup_logging初期化ブロックに対する模擬テスト test_setup_logging_initialization を追加し、カバレッジを100%に向上させ、全19テストのPASSを確認しました。",
        "changed_files": [
            "backend/tests/test_main_coverage.py"
        ]
    }
    print(f"Marking task {task_id_weaver1} as pass...")
    hub.mark_task_done(task_id_weaver1, "pass", report_weaver1)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
