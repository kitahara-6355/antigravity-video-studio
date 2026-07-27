import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 本セッションの Conversation ID
    conv_id = "24bf7ae4-2090-41d7-a3e6-3c38ab8af798"
    hub.register_flash_conversation_id(conv_id)
    
    task_id = "T-batch_4a2105-bug_hunter-000"
    report = {
        "message": "重複するテストファイルbackend/tests/test_mark_tasks_p27_multi5.pyの削除によるimport file mismatch解消。mark_tasks_p27_multi5.pyへのtry-exceptブロック追加と具体的例外（ValueError, KeyError等）キャッチおよびsys.exit(1)の導入。対応するテストの修正。",
        "changed_files": [
            "backend/agents/orchestration/mark_tasks_p27_multi5.py",
            "tests/test_mark_tasks_p27_multi5.py",
            "backend/tests/test_mark_tasks_p27_multi5.py"
        ]
    }
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)

    # 心拍更新 (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
