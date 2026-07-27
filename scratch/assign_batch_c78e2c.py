import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_c78e2c-bug_hunter-000": "0eb50337-5144-4abf-ae45-fbfde7a1a44a",
    "T-batch_c78e2c-bug_hunter-001": "1399c4d5-e4eb-44ca-bb3f-e5252aa29d99",
    "T-batch_c78e2c-bug_hunter-002": "411f46ca-2ce5-4540-8de5-b9879a79a61b",
    "T-batch_c78e2c-bug_hunter-003": "8317397d-5059-4481-8cf3-715237ceb5b9",
    "T-batch_c78e2c-bug_hunter-004": "dc66fc4a-4957-4902-9590-9bce5186c4c0",
    "T-batch_c78e2c-bug_hunter-005": "65c86f00-5ab7-4d69-943e-546990f0480e"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
