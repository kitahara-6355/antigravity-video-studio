# -*- coding: utf-8 -*-
import sys
import os
from pathlib import Path
import json

# Set correct paths for sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 1. Update heartbeat first (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    
    # 2. Get batch details
    TASK_QUEUE_PATH = PROJECT_ROOT / "backend" / "agents" / "orchestration" / "task_queue.json"
    if not TASK_QUEUE_PATH.exists():
        print("Task queue file not found.")
        return
        
    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    batch_id = queue.get("current_batch_id")
    tasks = queue.get("tasks", [])
    
    passed = sum(1 for t in tasks if t.get("status") == "pass")
    failed = sum(1 for t in tasks if t.get("status") == "fail")
    skipped = sum(1 for t in tasks if t.get("status") == "skip")
    total = len(tasks)
    
    results = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total
    }
    
    print(f"Submitting batch {batch_id} with results: {results}")
    
    if passed + failed + skipped == total and total > 0:
        # Submit batch report
        hub.submit_batch_report(batch_id, results)
        print("Batch report submitted successfully.")
        
        # Get next batch (mode STANDARD uses batch_size=6)
        state = hub.get_phase_state()
        phase = state.get("current_phase", 27)
        milestone = state.get("current_milestone", "M27.1")
        
        print(f"Getting next batch for Phase {phase} / {milestone} with size 6...")
        next_batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
        
        if next_batch:
            print(f"Successfully obtained next batch of size {len(next_batch)}")
        else:
            print("No more batches or tasks available.")
    else:
        print("Cannot submit batch yet. Some tasks are not completed.")

if __name__ == "__main__":
    main()
