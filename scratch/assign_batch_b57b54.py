import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_b57b54-bug_hunter-000": "89f5f1ce-caf9-44a8-b84e-01861d2646ac",
    "T-batch_b57b54-bug_hunter-001": "22aba8f5-3cbc-49a3-b05a-d42a99ddc526",
    "T-batch_b57b54-bug_hunter-002": "45ed9cdc-651a-41dd-b0fd-153dc5c59b75",
    "T-batch_b57b54-bug_hunter-003": "5c2fd013-2fc0-4ae6-b23b-83ad3623b05d",
    "T-batch_b57b54-bug_hunter-004": "f0954ea9-ef62-4cf2-899d-35ba383cd81a",
    "T-batch_b57b54-bug_hunter-005": "993c26f7-7053-45a0-839d-235265fd9595"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
