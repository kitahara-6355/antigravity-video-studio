import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

with open("backend/agents/orchestration/task_queue.json", "r", encoding="utf-8") as f:
    queue = json.load(f)

for task in queue.get("tasks", []):
    print(f"ID: {task['id']}, Status: {task['status']}, Module: {task.get('target_module')}")
