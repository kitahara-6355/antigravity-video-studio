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
    
    # 1. バッチ報告
    batch_id = "batch_b5fd13"
    print(f"Submitting report for batch: {batch_id}")
    hub.submit_batch_report(batch_id, {
        "passed": 4,
        "failed": 0,
        "skipped": 2,
        "total": 6
    })
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Submission ---")
    print(status.get("formatted", ""))
    
    # 2. 次のバッチ取得
    print("Getting next batch...")
    phase_state = hub.get_phase_state()
    current_milestone = phase_state.get("current_milestone", "M27.2")
    current_phase = phase_state.get("current_phase", 27)
    print(f"Current phase: {current_phase}, milestone: {current_milestone}")
    
    next_batch = hub.get_next_batch(phase=current_phase, milestone=current_milestone, batch_size=6)
    
    if not next_batch:
        print("No next batch. Session complete.")
    else:
        print(f"Next batch loaded: {len(next_batch)} tasks.")
        
if __name__ == "__main__":
    main()
