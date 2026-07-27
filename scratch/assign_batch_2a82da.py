import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_2a82da-bug_hunter-000": "37b7bd66-5ec2-49b5-9331-6eeb2875d86b",
    "T-batch_2a82da-bug_hunter-001": "b08a185d-9b30-416e-8f7d-ac18971cf306",
    "T-batch_2a82da-bug_hunter-002": "a278b84d-0f13-414a-952a-67e5ed4c7709",
    "T-batch_2a82da-bug_hunter-003": "eebd69d2-722e-4c9b-b8e5-0ccfa58451ce",
    "T-batch_2a82da-bug_hunter-004": "c657e287-c518-4524-b89f-eb50cefe1d7c",
    "T-batch_2a82da-bug_hunter-005": "7824e96b-b7a2-4b07-88e0-558e90a7867e"
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
