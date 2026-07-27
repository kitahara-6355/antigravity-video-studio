import sys
import os
import json
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.orchestrator import TASK_QUEUE_PATH, _read_json, _write_json

def assign_subagents(mappings: dict, task_queue_path: str = TASK_QUEUE_PATH) -> bool:
    queue = _read_json(task_queue_path)
    changed = False
    for task in queue.get("tasks", []):
        if task["id"] in mappings:
            task["assigned_agent"] = mappings[task["id"]]
            changed = True
            
    if changed:
        _write_json(task_queue_path, queue)
        print("Assigned subagents in task_queue.")
    else:
        print("No tasks matched mappings.")
    return changed

def main():
    hub = OrchestrationHub()
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. サブエージェントの割り当て
    mappings = {
        "T-batch_dab59b-thumbnail-000": "62005919-d6d4-4130-97eb-63eef3d9ae1c",
        "T-batch_dab59b-thumbnail-001": "8afc41b5-db5a-4b0b-975b-afe3ee63e443",
        "T-batch_dab59b-test_weaver-000": "d88afe50-e718-49b8-94dd-37ee0fd19a2c",
        "T-batch_dab59b-test_weaver-001": "5ec145d8-14e3-4a98-90ba-b39a5b8ed0cb",
        "T-batch_dab59b-bug_hunter-000": "208de9c1-9953-4273-a699-edfb9500cecc",
        "T-batch_dab59b-refactor-000": "9ef2f107-16e2-4d5f-a863-586a77e1d946"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
