import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

from backend.agents.orchestration.orchestrator import OrchestrationHub

def main():
    hub = OrchestrationHub()
    state = hub.get_phase_state()
    print(f"Phase State: {state}")
    
    phase = state["current_phase"]
    milestone = state["current_milestone"]
    
    # 次のバッチを取得 (batch_size=6)
    batch = hub.get_next_batch(phase, milestone, batch_size=6)
    print(f"Next Batch count: {len(batch)}")
    for t in batch:
        print(f"Task ID: {t['id']}, Target: {t['target_module']}")
        
    status = hub.generate_flash_status()
    print("---STATUS_START---")
    print(status["formatted"])
    print("---STATUS_END---")
    print(f"archive_urgency: {status.get('archive_urgency')}")

if __name__ == "__main__":
    main()
