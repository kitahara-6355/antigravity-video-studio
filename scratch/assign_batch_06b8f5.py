import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping for batch_06b8f5
    module_to_agent = {
        "agents/orchestration/wave_scheduler.py": "41d11fb6-e5f7-42f2-9447-9667b9ee480b",
        "verify_council_v2.py": "8a538d97-a608-4d60-86f1-3c5fca004d79",
        "agents/orchestration/flash_assign_subagents_8.py": "72d6169a-415f-4724-a11f-32da73572ba3",
        "agents/orchestration/run_session_end.py": "83683996-d901-46d9-b32b-ad26a4d1e296",
        "tests/_e2e_cycle3.py": "7080f60b-12dd-48bf-bc3d-0da1e8688e6c",
        "agents/council_graph.py": "ea879c3c-cda1-4477-8361-11540ddb097c"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_06b8f5" in task_id:
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
        print(f"Successfully assigned {assigned_count} tasks in batch_06b8f5.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
