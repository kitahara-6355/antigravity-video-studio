# -*- coding: utf-8 -*-
import json
from pathlib import Path

queue_path = Path("c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/task_queue.json")

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

updated = False
for task in queue.get("tasks", []):
    if task["id"] == "T-batch_a43c84-thumbnail-005":
        task["status"] = "pending"
        task["completed_at"] = None
        updated = True
        print("Updated task T-batch_a43c84-thumbnail-005 status to pending.")
        break

if updated:
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
