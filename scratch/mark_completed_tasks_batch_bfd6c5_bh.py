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
    task_id = "T-batch_bfd6c5-bug_hunter-000"
    report = {
        "message": "routers/smartcut.py 内の generate_smartcut_thumbnail エンドポイントにおける例外時の agent.stop() 呼び出し漏れを try-finally で修正し、リソースリークを防ぐように改善。テスト test_smartcut_thumbnail_agent_stop_on_exception を追加し全テストPASSを確認しました。",
        "changed_files": [
            "backend/routers/smartcut.py",
            "backend/tests/test_smartcut_thumbnail.py"
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
