import json
from pathlib import Path

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_6de532-bug_hunter-000": "df29a3df-ea65-400e-8159-fe873038b5eb",
    "T-batch_6de532-bug_hunter-001": "be8791a8-9fcb-4bc9-a3ba-b79898b9ece9",
    "T-batch_6de532-bug_hunter-002": "efa4bc6a-c4bb-401c-99a0-533a893d1fc5",
    "T-batch_6de532-bug_hunter-003": "732aa0e9-6ef3-4bb4-9380-448581ea716c",
    "T-batch_6de532-bug_hunter-004": "da0fb8de-c834-434a-abe5-fbfed57d3fa9",
    "T-batch_6de532-bug_hunter-005": "8a1013a9-de45-4122-962f-b40720599be5"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        # reset started_at to now, since we actually started them just now
        from datetime import datetime, timezone
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
