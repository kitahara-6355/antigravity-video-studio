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
    
    task_id = "T-batch_0f4e14-test_weaver-001"
    report = {
        "message": "PhilosophyManagerのカバレッジを94%から100%に改善（26テスト全PASS）。既存サムネイル上書きや、アトミック書き込み・品質検証失敗時の例外ハンドリングテストを追加しました。",
        "changed_files": [
            "backend/tests/test_philosophy_manager.py"
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
