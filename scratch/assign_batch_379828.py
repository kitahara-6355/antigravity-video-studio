import sys
from pathlib import Path
import json

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
    hub.register_flash_conversation_id("78b44067-a11c-4c04-9106-db3d8f632741")
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. サブエージェントの割り当て
    mappings = {
        "T-batch_379828-thumbnail-000": "ac6c17bf-764c-44ed-b141-c2a8c43efff4",
        "T-batch_379828-thumbnail-001": "2374c635-c348-4816-b0fb-56b8a076548c",
        "T-batch_379828-test_weaver-000": "d46c18f8-05ee-4235-aef2-0f8e0c06b9cd",
        "T-batch_379828-test_weaver-001": "d1c0e87c-182b-42b3-aa15-d0026e4133eb",
        "T-batch_379828-bug_hunter-000": "0f4e713b-afb6-46c5-a35f-b92ad4d72377",
        "T-batch_379828-refactor-000": "c1cd836d-066b-44b8-91c3-6b3a243bb5f8"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
