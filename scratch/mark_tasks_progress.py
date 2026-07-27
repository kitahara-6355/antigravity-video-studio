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
    
    # 1. Mark T-batch_0f4e14-test_weaver-001 as pass
    task_id1 = "T-batch_0f4e14-test_weaver-001"
    report1 = {
        "message": "PhilosophyManagerのカバレッジを94%から100%に改善（26テスト全PASS）。既存サムネイル上書きや、アトミック書き込み・品質検証失敗時の例外ハンドリングテストを追加しました。",
        "changed_files": [
            "backend/tests/test_philosophy_manager.py"
        ]
    }
    print(f"Marking task {task_id1} as pass...")
    hub.mark_task_done(task_id1, "pass", report1)
    
    # 2. Mark T-batch_0f4e14-refactor-000 as pass
    task_id2 = "T-batch_0f4e14-refactor-000"
    report2 = {
        "message": "smartcut_worker.py のリファクタリングが完了。重複コードのヘルパー化、連続インデックスのグループ化ループの関数分割、命名改善を実施し、カバレッジ100%を維持して全53テストPASSを確認。",
        "changed_files": [
            "backend/agents/workers/smartcut_worker.py"
        ]
    }
    print(f"Marking task {task_id2} as pass...")
    hub.mark_task_done(task_id2, "pass", report2)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
