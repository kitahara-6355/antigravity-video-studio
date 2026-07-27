import json
import os

def main():
    queue_file = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json"
    if os.path.exists(queue_file):
        with open(queue_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            current_batch_id = data.get("current_batch_id")
            print(f"Current Batch ID: {current_batch_id}")
            
            tasks = data.get("tasks", [])
            active_tasks = [t for t in tasks if t.get("id", "").startswith(f"T-{current_batch_id}")]
            print(f"Active tasks found ({len(active_tasks)}):")
            for t in active_tasks:
                print(f"ID: {t.get('id')}")
                print(f"  Group: {t.get('group')}")
                print(f"  Level: {t.get('level')}")
                print(f"  Target: {t.get('target_module')}")
                print(f"  Status: {t.get('status')}")
                print(f"  Instruction: {t.get('instruction')[:150]}...")
                print("-" * 40)
    else:
        print("Task queue file not found.")

if __name__ == "__main__":
    main()
