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
        "T-batch_74fe9c-thumbnail-000": "1fb1d5c3-7f83-4642-b9cc-2f66092597fd",
        "T-batch_74fe9c-thumbnail-001": "9f23189d-be8b-4794-9494-efb258b29efe",
        "T-batch_74fe9c-test_weaver-000": "aae2f367-9ee8-4100-b424-72a27ff02da7",
        "T-batch_74fe9c-test_weaver-001": "8be6d61c-b797-4650-acee-279e5ea1b8be",
        "T-batch_74fe9c-bug_hunter-000": "a73bc916-ec82-4872-b83c-77965a6db623",
        "T-batch_74fe9c-refactor-000": "b5febf87-7ef5-46ff-b138-8a53b18cfe41"
    }

    changed = False
    for task in queue.get("tasks", []):
        task_id = task.get("id")
        if task_id in mappings:
            task["assigned_agent"] = mappings[task_id]
            changed = True

    if changed:
        with open(TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print("Assigned agent mapping updated in task_queue.json.")
    else:
        print("No task ID matched mapping.")

if __name__ == "__main__":
    main()
