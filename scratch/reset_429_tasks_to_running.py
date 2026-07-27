import json
import time
from pathlib import Path

def main():
    TASK_QUEUE_PATH = Path("backend/agents/orchestration/task_queue.json")
    if not TASK_QUEUE_PATH.exists():
        print("task_queue.json not found.")
        return

    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
        queue = json.load(f)

    target_tasks = [
        "T-batch_2a82da-bug_hunter-000",
        "T-batch_2a82da-bug_hunter-001",
        "T-batch_2a82da-bug_hunter-002",
        "T-batch_2a82da-bug_hunter-003",
        "T-batch_2a82da-bug_hunter-004",
        "T-batch_2a82da-bug_hunter-005"
    ]

    changed = False
    for task in queue.get("tasks", []):
        if task.get("id") in target_tasks:
            task["status"] = "running"
            task["assigned_agent"] = None
            task["result"] = None
            changed = True

    if changed:
        with open(TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        print("Failed 429 tasks reset to running state in task_queue.json.")
    else:
        print("No task ID matched for resetting.")

    # クールダウン状態の書き出し
    # 1時間32分 = 5520秒 + 安全マージン = 5700秒
    current_time = time.time()
    reset_timestamp = current_time + 5700
    cooldown_data = {
        "cooldown_active": True,
        "reset_timestamp": reset_timestamp,
        "reset_time_str": time.strftime("%Y-%m-%d %H:%M:%S JST", time.localtime(reset_timestamp))
    }
    
    cooldown_path = Path("scratch/cooldown_state.json")
    with open(cooldown_path, "w", encoding="utf-8") as f:
        json.dump(cooldown_data, f, ensure_ascii=False, indent=2)
    print(f"Cooldown state saved. Reset time set to: {cooldown_data['reset_time_str']}")

if __name__ == "__main__":
    main()
