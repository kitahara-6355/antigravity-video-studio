import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 1. thumbnail-001 タスクを pass マーク
    task_id = "T-batch_73b13b-thumbnail-001"
    try:
        hub.mark_task_done(task_id, "pass")
        print(f"Task {task_id} marked as pass.")
    except Exception as e:
        print(f"Error marking task {task_id}: {e}")
        
    # 2. 心拍更新
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")
    
    # 3. バッチ送信
    try:
        hub.submit_batch_report("batch_73b13b", {"passed": 6, "failed": 0, "total": 6})
        print("Batch batch_73b13b submitted successfully.")
    except Exception as e:
        print(f"Error submitting batch: {e}")
        
    # 4. 次のバッチを取得
    try:
        next_batch = hub.get_next_batch(phase=27, milestone="M27.1", batch_size=6)
        print(f"Next batch: {next_batch}")
    except Exception as e:
        print(f"Error getting next batch: {e}")
        
    # 5. ステータス出力
    try:
        status = hub.generate_flash_status()
        print("\n=== FLASH STATUS ===")
        print(status["formatted"])
        print("====================")
    except Exception as e:
        print(f"Error generating status: {e}")

if __name__ == "__main__":
    main()
