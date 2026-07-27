import sys
import os
import json

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("e35c44a6-10a1-43c9-8a32-d76439eb554b")
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク完了のマーク (thumbnail-000)
    hub.mark_task_done(
        "T-batch_0d3445-thumbnail-000",
        "pass",
        {
            "subagent_id": "0a14d307-5e85-4f15-a2ac-dfe1b1c764b3",
            "message": "history_manager.py および logo_manager.py の解像度1280x720/16:9/4MB未満などの画像品質自動検証および StageBoundAgent 連携DB永続化などのテストを追加。",
            "changed_files": ["backend/branding/history_manager.py", "backend/logo_manager.py"]
        }
    )
    print("Marked T-batch_0d3445-thumbnail-000 as pass.")
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
