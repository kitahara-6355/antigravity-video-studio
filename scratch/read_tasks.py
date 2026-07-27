import json
from pathlib import Path

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    for task in queue.get("tasks", []):
        if "batch_8ae6aa" in task["id"]:
            print(f"ID: {task['id']}")
            print(f"Module: {task.get('module_path')}")
            print(f"Status: {task.get('status')}")
            print(f"Assigned: {task.get('assigned_agent')}")
            print(f"Message: {task.get('message', '')[:100]}")
            print("-" * 40)

if __name__ == "__main__":
    main()
