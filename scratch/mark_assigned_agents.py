# -*- coding: utf-8 -*-
import sys
import os

# Insert project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from backend.agents.orchestration.orchestrator import TASK_QUEUE_PATH, _read_json, _write_json
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 1. Update heartbeat
    hub.flash_update_heartbeat()
    
    # 2. Update mappings
    mappings = {
        "T-batch_f3ea3e-thumbnail-000": "0cc76f8b-3978-4d5f-958d-2e56ec1a0785",
        "T-batch_f3ea3e-thumbnail-001": "c63baf7f-29d8-4c8b-9376-a5fdd71f1740",
        "T-batch_f3ea3e-test_weaver-000": "eb9bfe41-ae32-4776-8bbc-60e26405ab4d",
        "T-batch_f3ea3e-test_weaver-001": "6022b86e-a040-49ca-907b-d66594f28e86",
        "T-batch_f3ea3e-bug_hunter-000": "816f6afd-f3c9-4099-8a16-1e49df323f95",
        "T-batch_f3ea3e-refactor-000": "a07a62b7-ed22-4db0-9299-7c9c85b68c4a"
    }
    
    queue = _read_json(TASK_QUEUE_PATH)
    changed = False
    for task in queue.get("tasks", []):
        if task["id"] in mappings:
            task["assigned_agent"] = mappings[task["id"]]
            changed = True
            
    if changed:
        _write_json(TASK_QUEUE_PATH, queue)
        print("Assigned subagents in task_queue.")
    else:
        print("No tasks matched mappings.")
        
    # Generate status
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
