import sys
import os

# プロジェクトのルートを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # phase state
    state = hub.get_phase_state()
    print("--- Phase State ---")
    for k, v in state.items():
        print(f"{k}: {v}")
        
    # queue status
    queue = hub.get_queue_status()
    print("\n--- Queue Status ---")
    for k, v in queue.items():
        print(f"{k}: {v}")
        
    # flash status
    try:
        status = hub.generate_flash_status()
        print("\n--- Flash Status (formatted) ---")
        print(status.get("formatted", "N/A"))
        print("\n--- Archive Urgency ---")
        print(status.get("archive_urgency", "N/A"))
    except Exception as e:
        print(f"Error generating flash status: {e}")

if __name__ == "__main__":
    main()
