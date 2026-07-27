import sys
import os
import json

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク完了のマーク
    hub.mark_task_done(
        "T-batch_3f4c3a-test_weaver-001",
        "pass",
        {
            "subagent_id": "029ca7ab-fdf5-41d4-96e2-a1cb199fa174",
            "message": "tests/scratch/migrate_e2e_files.py テストカバレッジ改善完了。例外処理カバレッジを追加し100%に向上",
            "changed_files": ["backend/tests/scratch/test_migrate_e2e_files.py"]
        }
    )
    print("Marked T-batch_3f4c3a-test_weaver-001 as pass.")
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
