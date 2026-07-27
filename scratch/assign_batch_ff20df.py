import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping for batch_ff20df
    module_to_agent = {
        "verify_council_v2.py": "4166483a-2043-4407-9d0e-d9a173d5109d",
        "agents/orchestration/wave_scheduler.py": "99585ced-4fd3-43e9-823a-aa6aa81fc4ad",
        "agents/orchestration/flash_assign_subagents_8.py": "9b1f8bc3-5613-46fb-83dc-5fa8a98b8a2a",
        "agents/orchestration/run_session_end.py": "8497720f-9167-49d9-9f8c-e2ed9b7f1f32",
        "tests/_e2e_cycle3.py": "dbf77936-88df-4a33-a17b-c8c2332d95b0",
        "agents/council_graph.py": "447d44ab-2183-4aef-a5ee-4523e1494342"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_ff20df" in task_id:
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
        print(f"Successfully assigned {assigned_count} tasks in batch_ff20df.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
