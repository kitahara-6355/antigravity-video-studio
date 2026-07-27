import json
from pathlib import Path

def main():
    queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    for task in queue.get("tasks", []):
        if "batch_aef5fb" in task["id"]:
            print(f"Task ID: {task['id']}")
            print("Keys:", list(task.keys()))
            for k, v in task.items():
                if k not in ["result"]: # skip verbose results
                    print(f"  {k}: {v}")
            print("-" * 40)

if __name__ == "__main__":
    main()
