import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # thumbnail-001 完了マーク
    hub.mark_task_done("T-batch_a97ee3-thumbnail-001", "pass", {
        "message": "disk_manager.py, council_graph.py, combined_overlay.py の検証共通化とテスト追加。",
        "changed_files": [
            "backend/disk_manager.py",
            "backend/agents/council_graph.py",
            "backend/combined_overlay.py",
            "backend/tests/test_thumbnail_quality.py"
        ]
    })
    
    print("TASK_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
