# -*- coding: utf-8 -*-
import json

task_queue_path = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json"

with open(task_queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

print("Current Milestone:", queue.get("current_milestone"))
print("Current Batch ID:", queue.get("current_batch_id"))
print("Tasks summary:")
for task in queue.get("tasks", []):
    print(f"- ID: {task['id']}, Group: {task['group']}, Status: {task['status']}, Result: {task.get('result')}")
