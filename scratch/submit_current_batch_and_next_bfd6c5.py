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
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    batch_id = "batch_bfd6c5"
    summary = {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    }
    
    print(f"Submitting batch report for {batch_id}...")
    hub.submit_batch_report(batch_id, summary)
    print("Batch report submitted successfully.")
    
    print("Getting next batch...")
    # Mode: STANDARD -> batch_size=6
    next_batch = hub.get_next_batch(27, "M27.1", batch_size=6)
    print(f"Next batch loaded: {len(next_batch)} tasks.")
    
    # Save the updated task queue or details if any
    print("Next batch details:")
    print(json.dumps(next_batch, indent=2))
    
    # Show status
    status = hub.generate_flash_status()
    print("\n=== FLASH STATUS ===")
    print(status.get("formatted", "No formatted status available."))
    
if __name__ == "__main__":
    main()
