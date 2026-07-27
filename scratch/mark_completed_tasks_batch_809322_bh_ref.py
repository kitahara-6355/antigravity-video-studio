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
    
    # 1. Mark bug_hunter-000
    task_id_bh = "T-batch_809322-bug_hunter-000"
    report_bh = {
        "message": "scratch/mark_task_29_done.py において、ハードコードされた絶対パスを動的解決へ修正し、mainガード化・インポートの遅延化によりインポートキャッシュに起因するテスト干渉を解決。カバレッジ100%を達成し全4テストのPASSを確認しました。",
        "changed_files": [
            "backend/scratch/mark_task_29_done.py",
            "backend/tests/test_scratch_mark_task_29_done.py"
        ]
    }
    print(f"Marking task {task_id_bh} as pass...")
    hub.mark_task_done(task_id_bh, "pass", report_bh)

    # 2. Mark refactor-000
    task_id_ref = "T-batch_809322-refactor-000"
    report_ref = {
        "message": "tests/_check_api_ui_alignment.py において、変数名の命名改善、巨大な単一関数からヘルパー関数群への機能分割を行い、カバレッジ100%を維持したままテスト全PASSを確認しました。",
        "changed_files": [
            "backend/tests/_check_api_ui_alignment.py",
            "backend/tests/test_check_api_ui_alignment.py"
        ]
    }
    print(f"Marking task {task_id_ref} as pass...")
    hub.mark_task_done(task_id_ref, "pass", report_ref)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
