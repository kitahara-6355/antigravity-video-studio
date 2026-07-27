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
    
    task_id = "T-batch_4a2105-refactor-000"
    report = {
        "message": "未使用importの削除、タスクレポートのBATCH_TASKS定数配列へのデータ構造化とコード分離、mainからマーク処理を実行するmark_batch_tasks関数の抽出分割。カバレッジ100%（2 passed）テスト追加。",
        "changed_files": [
            "backend/agents/orchestration/mark_tasks_p27_batch_4d4133.py",
            "tests/test_mark_tasks_p27_batch_4d4133.py"
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
