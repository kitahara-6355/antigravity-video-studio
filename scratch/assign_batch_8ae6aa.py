import json
from pathlib import Path
from datetime import datetime, timezone

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

mapping = {
    "T-batch_8ae6aa-bug_hunter-000": "411f46ca-2ce5-4540-8de5-b9879a79a61b",  # verify_council_v2.py
    "T-batch_8ae6aa-bug_hunter-001": "0eb50337-5144-4abf-ae45-fbfde7a1a44a",  # wave_scheduler.py
    "T-batch_8ae6aa-bug_hunter-002": "1399c4d5-e4eb-44ca-bb3f-e5252aa29d99",  # flash_assign_subagents_8.py
    "T-batch_8ae6aa-bug_hunter-003": "8317397d-5059-4481-8cf3-715237ceb5b9",  # tests/_e2e_cycle3.py
    "T-batch_8ae6aa-bug_hunter-004": "dc66fc4a-4957-4902-9590-9bce5186c4c0",  # run_session_end.py
    "T-batch_8ae6aa-bug_hunter-005": "65c86f00-5ab7-4d69-943e-546990f0480e"   # agents/council_graph.py
}

for task in queue.get("tasks", []):
    task_id = task["id"]
    if task_id in mapping:
        task["assigned_agent"] = mapping[task_id]
        task["started_at"] = datetime.now(timezone.utc).isoformat()
        print(f"Assigned task {task_id} to agent {mapping[task_id]}")

with open(queue_path, "w", encoding="utf-8") as f:
    json.dump(queue, f, ensure_ascii=False, indent=2)
