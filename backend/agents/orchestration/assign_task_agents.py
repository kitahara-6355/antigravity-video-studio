import sys
import json
import os

# プロジェクトルートおよび backend ディレクトリを PYTHONPATH に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration.atomic_io import FileLock, safe_read_json, atomic_write_json
from backend.agents.orchestration.hub_common import TASK_QUEUE_PATH

def main():
    if len(sys.argv) < 2:
        # Read from stdin
        try:
            stdin_data = sys.stdin.read()
            assignments = json.loads(stdin_data)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON from stdin: {e}")
            sys.exit(1)
        except OSError as e:
            print(f"Failed to read stdin: {e}")
            sys.exit(1)
    else:
        arg = sys.argv[1]
        if os.path.exists(arg) and arg.endswith(".json"):
            try:
                with open(arg, "r", encoding="utf-8") as f:
                    assignments = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON from file {arg}: {e}")
                sys.exit(1)
            except OSError as e:
                print(f"Failed to read JSON from file {arg}: {e}")
                sys.exit(1)
        else:
            try:
                assignments = json.loads(arg)
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON argument: {e}")
                sys.exit(1)

    if not isinstance(assignments, dict):
        print("Invalid assignments format: Expected a JSON object (dictionary)")
        sys.exit(1)

    lock_path = TASK_QUEUE_PATH.with_suffix(".json.lock")
    with FileLock(str(lock_path), timeout=60.0):
        queue = safe_read_json(str(TASK_QUEUE_PATH), {})
        changed = False
        for task in queue.get("tasks", []):
            tid = task.get("id")
            if tid in assignments:
                task["assigned_agent"] = assignments[tid]
                changed = True
        if changed:
            atomic_write_json(str(TASK_QUEUE_PATH), queue)
            print(f"Successfully updated {len(assignments)} assigned_agents in task_queue.json")
        else:
            print("No matching tasks found to update.")

if __name__ == "__main__":
    main()
