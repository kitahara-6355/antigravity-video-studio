import sys
import json
import os
from pathlib import Path

# プロジェクトルートをsys.pathに追加
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from backend.agents.orchestration.update_assigned_agents import update_tasks, load_task_queue, save_task_queue, DEFAULT_QUEUE_PATH
except ImportError as e:
    sys.path.insert(0, str(project_root / "backend"))
    from agents.orchestration.update_assigned_agents import update_tasks, load_task_queue, save_task_queue, DEFAULT_QUEUE_PATH

mapping = {
  "T-batch_521171-bug_hunter-000": "46b38de6-e8db-4121-989c-84826cd38273",
  "T-batch_521171-bug_hunter-001": "d2e5ef55-20d5-4658-9eb5-56498641cf0a",
  "T-batch_521171-bug_hunter-002": "7ca7d95d-5508-4901-a6f1-a9405872d20a",
  "T-batch_521171-bug_hunter-003": "d2d6d590-b286-45e4-8f58-a8b3b73239dc",
  "T-batch_521171-bug_hunter-004": "191adf84-7581-4b8e-8719-f2445cdaf751",
  "T-batch_521171-bug_hunter-005": "8e6ebab8-200e-476a-aadf-ffa15bf60a4b"
}

def main():
    try:
        queue_data = load_task_queue(DEFAULT_QUEUE_PATH)
        updated_queue, is_updated = update_tasks(queue_data, mapping)
        if is_updated:
            save_task_queue(DEFAULT_QUEUE_PATH, updated_queue)
            print("Successfully updated assigned_agents in task_queue.json")
        else:
            print("No tasks updated")
    finally:
        # 自己削除
        try:
            os.remove(__file__)
            print("Temporary script deleted.")
        except Exception as e:
            print(f"Warning: Failed to delete temporary script: {e}")

if __name__ == "__main__":
    main()
