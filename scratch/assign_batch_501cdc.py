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
        "T-batch_501cdc-thumbnail-000": "bbeadd53-15e0-4dc4-a040-23ba709c5de9",
        "T-batch_501cdc-thumbnail-001": "a787908e-ca9e-4d23-b967-8b508bbf809a",
        "T-batch_501cdc-test_weaver-000": "8be4d9bc-d65f-4fda-9b2c-32e731ee6a08",
        "T-batch_501cdc-test_weaver-001": "0fe3d09b-336e-4440-ac4c-65b64f554747",
        "T-batch_501cdc-bug_hunter-000": "b42e4c38-04ac-4561-8686-2eb61e6f9bbc",
        "T-batch_501cdc-refactor-000": "487bbf14-db4a-431b-b7f1-953ece3f3f47"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
