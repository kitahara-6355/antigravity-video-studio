import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    
    # 完了マーク
    task_id = "T-batch_b2b7f6-bug_hunter-009"
    report = {
        "message": "デフォルトの定数値とテスト期待値の不一致修正、およびテスト追加",
        "changed_files": [
            "backend/tests/test_flash_runner_next_batch.py"
        ]
    }
    hub.mark_task_done(task_id, "pass", report)
    print(f"Marked task {task_id} as done.")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

if __name__ == '__main__':
    main()
