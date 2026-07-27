import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping
    module_to_agent = {
        "verify_council_v2.py": "411f46ca-2ce5-4540-8de5-b9879a79a61b",
        "agents/orchestration/wave_scheduler.py": "0eb50337-5144-4abf-ae45-fbfde7a1a44a",
        "agents/orchestration/flash_assign_subagents_8.py": "1399c4d5-e4eb-44ca-bb3f-e5252aa29d99",
        "agents/orchestration/run_session_end.py": "dc66fc4a-4957-4902-9590-9bce5186c4c0",
        "tests/_e2e_cycle3.py": "8317397d-5059-4481-8cf3-715237ceb5b9",
        "agents/council_graph.py": "65c86f00-5ab7-4d69-943e-546990f0480e"
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
                print(f"Assigned {task_id} ({target}) -> Agent {agent_id}")
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
