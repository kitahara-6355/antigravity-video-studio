# -*- coding: utf-8 -*-
"""Module for assigning agents to subtasks in the task queue.

This module reads the task queue JSON file, iterates through the tasks,
and maps specific tasks to assigned agent IDs using a predefined mappings dict.
If any task's assigned_agent differs from the mapping, it updates the task
and writes the updated queue back to the task queue file.
"""
import sys
import json
import traceback
sys.path.insert(0, '.')
from backend.agents.orchestration.orchestrator import TASK_QUEUE_PATH, _read_json, _write_json

mappings = {
    "T-batch_d36694-bug_hunter-000": "b3e3cc4b-6fb3-4079-a157-91c8e37ece76",
    "T-batch_d36694-bug_hunter-001": "5578de1f-7280-4e31-877e-7ea4dad1f71f",
    "T-batch_d36694-bug_hunter-002": "af1b4835-8384-4799-9dc9-72b307f4b626",
    "T-batch_d36694-bug_hunter-003": "ee06c8cb-d79c-404a-b4b9-822c79812b72",
    "T-batch_d36694-bug_hunter-004": "2e90ce2d-fc1c-4548-ad5f-5c17e0121d9b",
    "T-batch_d36694-bug_hunter-005": "4388911f-7a8e-4bcd-a87e-d2cd2dff8ad6"
}

def main() -> int:
    """Main execution function to update the task queue with assigned agents.

    Returns:
        int: 0 if successful (even if no tasks were updated), 1 if an error occurred.
    """
    try:
        queue = _read_json(TASK_QUEUE_PATH)
    except FileNotFoundError as e:
        print(f"Error: Task queue file not found. Detail: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse task queue JSON. Detail: {e}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as e:
        print(f"Error: Encoding error occurred when reading task queue file. Detail: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"Error: Permission denied when reading task queue file. Detail: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: OS error occurred when reading task queue file: {e}", file=sys.stderr)
        return 1

    if not isinstance(queue, dict):
        print("Error: Task queue content is not a valid JSON object.", file=sys.stderr)
        return 1

    tasks = queue.get("tasks", [])
    if not isinstance(tasks, list):
        print("Error: 'tasks' key in task queue is not a list.", file=sys.stderr)
        return 1

    changed = False
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            print(f"Error: Task at index {i} is not a valid JSON object.", file=sys.stderr)
            return 1
        if "id" not in task:
            print(f"Error: Task at index {i} is missing 'id' key.", file=sys.stderr)
            return 1
        
        task_id = task["id"]
        if not isinstance(task_id, str):
            print(f"Error: Invalid task ID type at index {i}. Expected string, got {type(task_id).__name__}.", file=sys.stderr)
            return 1
            
        if task_id in mappings:
            new_agent = mappings[task_id]
            if task.get("assigned_agent") != new_agent:
                task["assigned_agent"] = new_agent
                changed = True
            
    if changed:
        try:
            _write_json(TASK_QUEUE_PATH, queue)
            print("Updated task queue with assigned agents.")
        except PermissionError as e:
            print(f"Error: Permission denied when writing task queue file. Detail: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Error: OS error occurred when writing task queue file: {e}", file=sys.stderr)
            return 1
    else:
        print("No tasks updated.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
