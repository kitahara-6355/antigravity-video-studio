import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_7d265f-bug_hunter-000": "b7e4ea48-a0af-4cee-b1c0-a49aaebcdb66",
    "T-batch_7d265f-bug_hunter-001": "834456eb-659b-4530-8689-48288a399f7b",
    "T-batch_7d265f-bug_hunter-002": "113f5cbf-fdd9-408a-b453-fe43bc4c54a7",
    "T-batch_7d265f-bug_hunter-003": "ff100028-e50c-44ab-b1cb-95eba69b740f",
    "T-batch_7d265f-bug_hunter-004": "30c3deb1-2480-4da8-928c-5428660d1439",
    "T-batch_7d265f-bug_hunter-005": "66b13fbc-61cf-49ac-aa4d-c2f99734e2df",
    "T-batch_7d265f-bug_hunter-006": "35d5f3ee-e0b9-48a0-9939-8c4a4fdc1533",
    "T-batch_7d265f-bug_hunter-007": "c8b4dfff-8914-44a9-9155-82ac209a4fb0",
    "T-batch_7d265f-bug_hunter-008": "ec56b7e3-1db4-45d6-9ef7-d221df23deb6",
    "T-batch_7d265f-bug_hunter-009": "42bf0926-eaa6-4fc5-a01d-2a0d38c1b83b"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
