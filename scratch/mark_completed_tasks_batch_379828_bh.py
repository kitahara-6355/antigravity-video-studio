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
    
    # Mark bug_hunter-000
    task_id = "T-batch_379828-bug_hunter-000"
    report = {
        "message": "verify_council.py において非推奨の Nexus インポートを削除し、ADKの run_council で実行するように修正。新規テスト test_verify_council.py を作成し全24テストのPASSおよびカバレッジ100%を確認しました。",
        "changed_files": [
            "backend/verify_council.py",
            "backend/tests/test_verify_council.py"
        ]
    }
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
