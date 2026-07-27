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
        "T-batch_809322-thumbnail-000": "52ac78a1-5ca1-4016-86cf-cbc9b85c1f89",
        "T-batch_809322-thumbnail-001": "87b024a5-4fde-4ca7-9432-de6954da3513",
        "T-batch_809322-test_weaver-000": "9ea6dc5f-9f24-400e-9811-19546a0e8df8",
        "T-batch_809322-test_weaver-001": "13680391-fcb6-4bef-8477-f75a76e230db",
        "T-batch_809322-bug_hunter-000": "5b052d57-a6bd-4511-9012-1906287584ca",
        "T-batch_809322-refactor-000": "3961cac7-94e1-4de8-abeb-b930cf4b9bce"
    }
    assign_subagents(mappings)
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
