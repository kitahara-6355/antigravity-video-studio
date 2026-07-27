import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to new Agent ID mapping
    module_to_agent = {
        "verify_council_v2.py": "7bde409d-acbe-4223-b8c3-05e06ae7d0cd",
        "agents/orchestration/wave_scheduler.py": "23dda9f1-494c-4bcc-a9d1-d093faca2c1d",
        "agents/orchestration/flash_assign_subagents_8.py": "e884e0e5-4b30-4673-ab3f-b64c5cb859d2",
        "agents/orchestration/run_session_end.py": "daa63e1b-9fd2-4cf3-ad5b-9ee73fbc48d9",
        "tests/_e2e_cycle3.py": "c9dd119a-ed08-4da8-863b-1c265a061390",
        "agents/council_graph.py": "14bf8240-5ddd-482e-a87e-aadfdbdbd52c"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_aef5fb" in task_id:
            target = task.get("target_module")
            if target in module_to_agent:
                agent_id = module_to_agent[target]
                task["assigned_agent"] = agent_id
                task["started_at"] = datetime.now(timezone.utc).isoformat()
                print(f"Assigned {task_id} ({target}) -> New Agent {agent_id}")
                assigned_count += 1
            else:
                print(f"Warning: No agent mapped for module {target} in task {task_id}")
                
    if assigned_count > 0:
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print(f"Successfully assigned {assigned_count} tasks in batch_aef5fb.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
