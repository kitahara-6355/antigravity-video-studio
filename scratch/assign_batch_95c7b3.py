import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_95c7b3-bug_hunter-000": "f5c0d66c-72ab-464e-a717-46ea2bd95b30",
    "T-batch_95c7b3-bug_hunter-001": "e7d5ee29-c861-487d-a471-85a31bff83d0",
    "T-batch_95c7b3-bug_hunter-002": "36968590-9a44-462c-9aff-3fb375070522",
    "T-batch_95c7b3-bug_hunter-003": "ec61f06b-99d7-4ce0-81a2-99cca27a2147",
    "T-batch_95c7b3-bug_hunter-004": "07d321be-57c6-4397-ac4b-c673b60ee17f",
    "T-batch_95c7b3-bug_hunter-005": "4524fe9b-2dac-4e6b-b38d-77b3efad5beb",
    "T-batch_95c7b3-bug_hunter-006": "ff75b1a6-a3c9-45f0-95a8-105ad8420ba8",
    "T-batch_95c7b3-bug_hunter-007": "f959a1e0-92bb-4f0e-a120-203b32b30219",
    "T-batch_95c7b3-bug_hunter-008": "359561a0-f306-47cb-ac42-a815309973ec",
    "T-batch_95c7b3-bug_hunter-009": "0989a00d-6aba-4232-af6d-4f9c50abf115"
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
