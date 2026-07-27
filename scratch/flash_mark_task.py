import sys
import os
import json

sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation\backend")
sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation")

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "d040406a-753e-4388-b488-b525cd358e85"
    hub.register_flash_conversation_id(conv_id)
    
    # 1. Mark test_weaver-000
    task_id_weaver = "T-batch_b53eed-test_weaver-000"
    report_weaver = {
        "message": "test_analyst.py を追加し、エッジケースや境界値テストを含むユニットテストを20ケース実装。カバレッジ100%を維持。",
        "changed_files": [
            "backend/tests/test_analyst.py"
        ]
    }
    print(f"Marking task {task_id_weaver} as pass...")
    hub.mark_task_done(task_id_weaver, "pass", report_weaver)

    # 2. Mark refactor-000
    task_id_ref = "T-batch_b53eed-refactor-000"
    report_ref = {
        "message": "admin_setup_router.py 内のラムダ診断処理の関数分割、マジックナンバー自己記述化、リネーム命名改善。カバレッジ100%を維持しつつ52テストPASSを確認。",
        "changed_files": [
            "backend/routers/admin_setup_router.py"
        ]
    }
    print(f"Marking task {task_id_ref} as pass...")
    hub.mark_task_done(task_id_ref, "pass", report_ref)

    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
