import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_74e4bc-bug_hunter-000": "edddbf52-2208-4b5b-83a1-d9000cc535ca",
    "T-batch_74e4bc-bug_hunter-001": "b61fe13b-05ac-40ed-93a4-ee802377832b",
    "T-batch_74e4bc-bug_hunter-002": "82acd0e3-7313-470b-8cea-a975a8985da4",
    "T-batch_74e4bc-bug_hunter-003": "271425f6-fb85-4c6a-8278-8f6d0f4a992e",
    "T-batch_74e4bc-bug_hunter-004": "108dae35-e447-49d6-804b-1b6bb51afe7c",
    "T-batch_74e4bc-bug_hunter-005": "339783e9-28d1-4fb9-af9b-9583f4cfb931"
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
