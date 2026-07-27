import json
from pathlib import Path

def throttle_tasks():
    queue_path = Path(r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json")
    if not queue_path.exists():
        print("Error: task_queue.json not found")
        return
        
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
        
    tasks = queue.get("tasks", [])
    running_tasks = [t for t in tasks if t["status"] == "running"]
    print(f"Total running tasks found: {len(running_tasks)}")
    
    # 最初の3件だけをrunningとして維持し、他をpendingにする
    keep_running_limit = 3
    running_count = 0
    modified_count = 0
    
    for t in tasks:
        if t["status"] == "running":
            if running_count < keep_running_limit:
                running_count += 1
                print(f"Keeping running: {t['id']} ({t['target_module']})")
            else:
                t["status"] = "pending"
                modified_count += 1
                print(f"Resetting to pending: {t['id']} ({t['target_module']})")
                
    if modified_count > 0:
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print(f"Successfully modified {modified_count} tasks to 'pending'.")
    else:
        print("No tasks modified.")

if __name__ == "__main__":
    throttle_tasks()
