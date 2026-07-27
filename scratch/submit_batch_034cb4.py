import sys
from pathlib import Path
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # Register our conversation ID
    conv_id = "ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1"
    hub.register_flash_conversation_id(conv_id)
    
    batch_id = "batch_034cb4"
    summary = {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    }
    
    print(f"Submitting batch report for {batch_id}...")
    try:
        hub.submit_batch_report(batch_id, summary)
        print("Batch report submitted successfully.")
    except Exception as e:
        print(f"Error submitting batch report: {e}")
        sys.exit(1)
        
    print("Getting next batch...")
    # Phase 33, milestone M33.1, batch_size=6
    try:
        next_batch = hub.get_next_batch(33, "M33.1", batch_size=6)
        print(f"Next batch loaded: {len(next_batch) if next_batch else 0} tasks.")
        if next_batch:
            print("Next batch details:")
            print(json.dumps(next_batch, indent=2))
    except Exception as e:
        print(f"Error getting next batch: {e}")
        
    # Show status
    try:
        status = hub.generate_flash_status()
        print("\n=== FLASH STATUS ===")
        print(status.get("formatted", "No formatted status available."))
    except Exception as e:
        print(f"Error generating flash status: {e}")

if __name__ == "__main__":
    main()
