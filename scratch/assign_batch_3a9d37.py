import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_3a9d37-bug_hunter-000": "fddc6244-8148-4922-84d5-d4b25b3f7c58",
    "T-batch_3a9d37-bug_hunter-001": "76af5cf1-4305-4bb7-b5c5-582994e998d4",
    "T-batch_3a9d37-bug_hunter-002": "cabdbe82-8a6c-4047-93a3-85bc0487a2b6",
    "T-batch_3a9d37-bug_hunter-003": "1618c1c5-46ac-4907-8322-cb9b0e286191",
    "T-batch_3a9d37-bug_hunter-004": "86d885d8-8f33-4f74-9b24-56455fcba693",
    "T-batch_3a9d37-bug_hunter-005": "00366a45-3a71-46cd-b157-99f5cdf7b4f5"
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
