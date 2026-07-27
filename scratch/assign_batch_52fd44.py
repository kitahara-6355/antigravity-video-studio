import json
from pathlib import Path
from datetime import datetime, timezone

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    # Module to Agent ID mapping for batch_52fd44
    module_to_agent = {
        "error_reporter.py": "78207cef-d07c-4e79-89d6-02bd8d19a665",
        "agents/orchestration/learning_integration.py": "634b5613-3244-4e0e-94ff-c7209cada999",
        "scratch/get_next_batch.py": "bf5a19b6-3f48-43cf-bc84-b144c38b1475",
        "agents/director.py": "1796b6bd-0b03-404b-a00b-8f0f42679c0f",
        "plugins/report_generator_plugin.py": "8927c795-4a4b-4e43-b1c8-0f77425452df",
        "service_container.py": "4ccdb87d-77d6-41d3-844a-81ac1480a7ec"
    }
    
    assigned_count = 0
    for task in queue.get("tasks", []):
        task_id = task["id"]
        if "batch_52fd44" in task_id:
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
        print(f"Successfully assigned {assigned_count} tasks in batch_52fd44.")
    else:
        print("No tasks found/assigned.")

if __name__ == "__main__":
    main()
