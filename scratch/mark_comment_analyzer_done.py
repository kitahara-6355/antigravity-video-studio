# -*- coding: utf-8 -*-
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    task_id = "T-batch_0f4e14-bug_hunter-000"
    report = {
        "message": "services/comment_analyzer.py のバグ修正。広範な Exception を具体的な OSError/TypeError/ValueError に変更し、一時ファイルによるアトミックな書き込み・クリーンアップを導入。テスト追加を含め全19件PASS、技術負債2件(TD-236, TD-525)を解消。",
        "changed_files": [
            "backend/services/comment_analyzer.py",
            "backend/tests/test_shared/test_cov_comment_analyzer.py"
        ]
    }
    
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Task Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
