import sys
import json
from backend.agents.orchestration import OrchestrationHub

def main():
    try:
        hub = OrchestrationHub()
        # phase_state から現在の phase/milestone を取得
        state = hub.get_phase_state()
        phase = state.get("current_phase", 2)
        milestone = state.get("current_milestone", "M2.1")
        
        # バッチ取得 (プロファイルに基づいて batch_size=6)
        batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
        queue_status = hub.get_queue_status()
        
        result = {
            "batch": batch,
            "queue_status": queue_status,
            "phase": phase,
            "milestone": milestone
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()
