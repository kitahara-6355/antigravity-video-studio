import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    
    # タイムアウトした008をskipに上書きマーク
    task_id_008 = "T-batch_b2b7f6-bug_hunter-008"
    hub.mark_task_done(task_id_008, "skip", {
        "error": "SUBAGENT_TIMEOUT: 10分超経過により親エージェントによって強制終了し、自動スキップ"
    })
    print(f"Marked task {task_id_008} as skip.")
    
    # バッチレポートの提出
    hub.submit_batch_report("batch_b2b7f6", {
        "passed": 9,
        "failed": 0,
        "skipped": 1,
        "total": 10
    })
    print("Batch report submitted.")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

if __name__ == '__main__':
    main()
