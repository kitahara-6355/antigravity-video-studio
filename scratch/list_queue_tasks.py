import json
from pathlib import Path

queue_path = Path("backend/agents/orchestration/task_queue.json")
if queue_path.exists():
    with open(queue_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"Batch ID: {data.get('current_batch_id')}")
    print(f"Phase: {data.get('phase')}, Milestone: {data.get('milestone')}")
    tasks = data.get("tasks", [])
    print(f"Total tasks: {len(tasks)}")
    
    status_counts = {}
    for t in tasks:
        st = t.get("status")
        status_counts[st] = status_counts.get(st, 0) + 1
    print(f"Status counts: {status_counts}")
    
    print("\n--- Non-pass Tasks ---")
    for t in tasks:
        if t.get("status") != "pass":
            print(f"ID: {t.get('id')}")
            print(f"  Module: {t.get('target_module')}")
            print(f"  Status: {t.get('status')}")
            print(f"  Assigned Agent: {t.get('assigned_agent')}")
            if t.get("result"):
                print(f"  Result: {t.get('result')}")
else:
    print("Task queue not found.")
