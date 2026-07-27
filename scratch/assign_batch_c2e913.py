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
        "T-batch_c2e913-thumbnail-000": "9c9ccb07-01a6-4cc2-9550-098a6a039caf",
        "T-batch_c2e913-thumbnail-001": "03f99856-f65a-4e6a-82d0-81d0937b0341",
        "T-batch_c2e913-test_weaver-000": "6bbc4aaa-65ed-4ce0-bcff-0fb4720618c3",
        "T-batch_c2e913-test_weaver-001": "61ec24e7-b63a-4b6b-8177-6658c177f40c",
        "T-batch_c2e913-bug_hunter-000": "7b491bdd-471d-47a8-bf39-abb0edd2600a",
        "T-batch_c2e913-refactor-000": "174f816f-6ce7-4373-95b6-d66c4d6f1d7b"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
