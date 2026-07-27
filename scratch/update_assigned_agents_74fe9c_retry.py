import json
from pathlib import Path

def main():
    TASK_QUEUE_PATH = Path("backend/agents/orchestration/task_queue.json")
    if not TASK_QUEUE_PATH.exists():
        print("task_queue.json not found.")
        return

    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
        queue = json.load(f)

    mappings = {
        "T-batch_74fe9c-thumbnail-000": "22b2b8bc-5910-4f1f-8049-26ebe7a84474",
        "T-batch_74fe9c-thumbnail-001": "b78e05de-3019-4393-b9ef-d63497d34a02",
        "T-batch_74fe9c-bug_hunter-000": "abac0cec-727a-4610-bc6d-708a8515116b",
        "T-batch_74fe9c-refactor-000": "7ddc31ef-14c6-4089-abb0-29483f9f3bcb"
    }

    changed = False
    for task in queue.get("tasks", []):
        task_id = task.get("id")
        if task_id in mappings:
            task["assigned_agent"] = mappings[task_id]
            task["status"] = "running"
            changed = True

    if changed:
        with open(TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print("Assigned agent mappings for retried tasks updated in task_queue.json.")
    else:
        print("No task ID matched mapping.")

if __name__ == "__main__":
    main()
