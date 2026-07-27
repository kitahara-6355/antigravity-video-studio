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
        "T-batch_bfd6c5-thumbnail-000": "3b52f4a3-c3ed-4d4a-9710-d32f1347f57a",
        "T-batch_bfd6c5-thumbnail-001": "adf1bf9a-1941-45a0-8d6e-24bbfd2d4975",
        "T-batch_bfd6c5-test_weaver-000": "e631a65f-783b-45d6-8191-f36b4b8282c4",
        "T-batch_bfd6c5-test_weaver-001": "f074989b-db28-43b5-b4bf-2cac05743e6e",
        "T-batch_bfd6c5-bug_hunter-000": "aeb73743-7f11-4047-a3c4-7cbc80e99d58",
        "T-batch_bfd6c5-refactor-000": "90168a01-129a-4109-9bf7-f3f08a600d1b"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
