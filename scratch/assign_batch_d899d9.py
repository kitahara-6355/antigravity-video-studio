import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping for batch_d899d9
    module_to_agent = {
        "routers/pipeline_default_states.py": "db2fdbcb-d134-4bd9-8efd-687d062f364a",
        "agents/orchestration/mark_tasks_p27_multi13.py": "4f86ecf0-b38d-4f1a-bd01-2a5341c3fb58",
        "quality_gate_ai.py": "57192e87-687d-4448-b089-a63cb47c995a",
        "services/tdr_resolver.py": "2396446c-50bb-49a8-bb96-a56b1841c2e9",
        "utils/json_safe_io.py": "b264862b-8e71-4600-86b1-f3a749006738",
        "dispatch_enhancer.py": "749f2d5a-8839-444e-b8d8-0f9d6f4eb348"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_d899d9" in task_id:
            target = task.get("target_module")
            if target in module_to_agent:
                agent_id = module_to_agent[target]
                task["assigned_agent"] = agent_id
                task["started_at"] = datetime.now(timezone.utc).isoformat()
                print(f"Assigned {task_id} ({target}) -> Agent {agent_id}")
                assigned_count += 1
            else:
                print(f"Warning: No agent mapped for module {target} in task {task_id}")
                
    if assigned_count > 0:
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print(f"Successfully assigned {assigned_count} tasks in batch_d899d9.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
