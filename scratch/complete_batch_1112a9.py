import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    batch_id = "batch_1112a9"
    
    # 1. バッチ報告を提出
    print("Submitting batch report...")
    hub.submit_batch_report(batch_id, {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })
    print("Batch report submitted successfully.")
    
    # 2. 心拍を更新
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")
    
    # 3. 現在のフェーズ状態確認
    phase_state = hub.get_phase_state()
    phase = phase_state.get("current_phase", 27)
    milestone = phase_state.get("current_milestone", "M27.1")
    print(f"Current Phase: {phase}, Milestone: {milestone}")
    
    # 4. 次のバッチを取得
    print("Fetching next batch (batch_size=12)...")
    next_batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=12)
    if next_batch:
        print(f"Acquired next batch of size {len(next_batch)}")
        # タスク詳細を表示
        for t in next_batch:
            print(f" - Task: {t.get('id')}, Group: {t.get('group')}, Target: {t.get('target_module')}")
    else:
        print("No next batch returned. Phase completed or waiting for Opus.")
        
    # 5. ステータス情報を生成してダンプ
    status = hub.generate_flash_status()
    print("\n=== FLASH STATUS ===")
    print(status.get("formatted", ""))
    print("====================")

if __name__ == "__main__":
    main()
