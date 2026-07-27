import json
import os

def main():
    queue_file = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json"
    if os.path.exists(queue_file):
        with open(queue_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Print main keys
            print("Keys in queue file:", list(data.keys()))
            
            # Print active_batch keys and tasks
            active_batch = data.get("active_batch", {})
            print("Active Batch ID:", active_batch.get("id"))
            tasks = active_batch.get("tasks", [])
            print(f"Tasks in active_batch ({len(tasks)}):")
            for t in tasks:
                print(f"  - {t.get('id')}: {t.get('status')} (assigned: {t.get('assigned_agent')})")
                
            # Search everywhere in JSON for T-batch_9e2a02-thumbnail-000
            def search_id(obj, target_id):
                if isinstance(obj, dict):
                    if obj.get("id") == target_id:
                        return obj
                    for k, v in obj.items():
                        res = search_id(v, target_id)
                        if res:
                            return res
                elif isinstance(obj, list):
                    for item in obj:
                        res = search_id(item, target_id)
                        if res:
                            return res
                return None
            
            res = search_id(data, "T-batch_9e2a02-thumbnail-000")
            if res:
                print("\nFound target task in JSON:")
                print(json.dumps(res, indent=2))
            else:
                print("\nTarget task NOT found anywhere in JSON.")
    else:
        print("Task queue file not found.")

if __name__ == "__main__":
    main()
