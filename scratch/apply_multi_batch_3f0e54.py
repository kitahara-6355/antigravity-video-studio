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
    
    # 1. bug_hunter-000
    task_id_bh = "T-batch_3f0e54-bug_hunter-000"
    report_bh = {
        "message": "相対インポートの絶対パス化、main()全体へのtry-exceptブロック導入による例外発生時のsys.exit(1)エラーハンドリング強化。対応するテストの追加およびフィットネステストPASSを確認。",
        "changed_files": [
            "backend/agents/orchestration/mark_tasks_p27_multi10.py",
            "backend/tests/test_mark_tasks_p27_multi10.py"
        ]
    }
    print(f"Marking task {task_id_bh} as pass...")
    hub.mark_task_done(task_id_bh, "pass", report_bh)

    # 2. refactor-000
    task_id_ref = "T-batch_3f0e54-refactor-000"
    report_ref = {
        "message": "私的関数_get_evolution_log_path()のモジュール定数化と削除によるデッドコード削減、JSON読み込み処理の_read_json_file()ヘルパーへの関数分割、queryデフォルト値の定数化。カバレッジ100%（34 tests PASSED）を確認。",
        "changed_files": [
            "backend/routers/collaboration.py"
        ]
    }
    print(f"Marking task {task_id_ref} as pass...")
    hub.mark_task_done(task_id_ref, "pass", report_ref)

    # 心拍更新 (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
