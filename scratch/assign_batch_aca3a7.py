import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_aca3a7-bug_hunter-000": "e1932bd8-2df7-471a-a0e6-939eab17a330",
    "T-batch_aca3a7-bug_hunter-001": "32f48f93-6301-41aa-9dc8-c84afb55beb0",
    "T-batch_aca3a7-bug_hunter-002": "47db9f78-435e-49a1-92d4-ce8cd13ebe55",
    "T-batch_aca3a7-bug_hunter-003": "bf60ecfe-8e86-4bb6-8170-f930ffefb012",
    "T-batch_aca3a7-bug_hunter-004": "26acfd67-f7a8-45b6-8e3e-c9f03708707f",
    "T-batch_aca3a7-bug_hunter-005": "e6930875-41a5-4a5b-8821-bb2d20d31f1a"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        # reset started_at to now, since we actually started them just now
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
