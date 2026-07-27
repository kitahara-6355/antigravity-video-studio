import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping for batch_034cb4
    module_to_agent = {
        "scratch/get_next_batch.py": "126de810-4cb3-4d6f-948b-522db70eceb4",
        "error_reporter.py": "f1ef8f42-5028-4f71-9059-88d5e7651a02",
        "plugins/report_generator_plugin.py": "05c96165-0f3a-4b01-9cd2-d72b36331b42",
        "agents/director.py": "360cce0d-ec82-456d-9391-ca04bf86765d",
        "agents/orchestration/learning_integration.py": "21b81ffa-f793-4c47-927d-feda99c3aa4c",
        "service_container.py": "701830cf-7275-41a2-9538-20e2241faaf5"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_034cb4" in task_id:
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
        print(f"Successfully assigned {assigned_count} tasks in batch_034cb4.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
