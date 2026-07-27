import sys
import json
import os
sys.path.insert(0, '.')
sys.path.insert(0, './backend')
sys.path.insert(0, os.path.abspath('backend'))
from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 3:
        print("Usage: python submit_and_next.py <conversation_id> <batch_id> [passed] [failed]")
        sys.exit(1)
        
    conv_id = sys.argv[1]
    batch_id = sys.argv[2]
    passed = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    failed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conv_id)
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. バッチ完了報告
    results = {
        "passed": passed,
        "failed": failed,
        "skipped": 0,
        "total": passed + failed
    }
    hub.submit_batch_report(batch_id, results)
    print(f"Batch {batch_id} submitted.")
    
    # 3. 現在のフェーズ状態確認
    state = hub.get_phase_state()
    phase = state.get("current_phase", 27)
    milestone = state.get("current_milestone", "M27.1")
    
    # 4. 次のバッチを取得
    batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
    print("=== NEW BATCH ===")
    print(json.dumps(batch, ensure_ascii=False, indent=2))
    
    # 5. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
