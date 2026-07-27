import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 1. Update heartbeat first (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    print("Heartbeat updated successfully.")
    
    # 2. Generate and print status
    status = hub.generate_flash_status()
    print("\n=== FLASH STATUS ===")
    print(status.get("formatted", "No formatted status available."))
    
    # 3. Check transition urgency
    archive_urgency = status.get("archive_urgency")
    print(f"Archive Urgency: {archive_urgency}")
    
    # 4. Check current queue status
    queue = hub.get_queue_status()
    print("\n=== QUEUE STATUS ===")
    print(f"Current Batch ID: {queue.get('batch_id')}")
    print(f"Phase: {queue.get('phase')}, Milestone: {queue.get('milestone')}")
    
if __name__ == "__main__":
    main()
