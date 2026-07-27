import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any

DEFAULT_QUEUE_PATH = Path("backend/agents/orchestration/task_queue.json")

def parse_arguments(sys_args: List[str]) -> Dict[str, str]:
    """コマンドライン引数を検証し、JSONマッピングを辞書としてロードする。"""
    if len(sys_args) < 2:
        print("Usage: python update_assigned_agents.py '<json_mapping>'")
        sys.exit(1)
    try:
        data = json.loads(sys_args[1])
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON mapping format. {e}")
        sys.exit(1)
        
    if not isinstance(data, dict):
        print("Error: JSON mapping must be a key-value dictionary object.")
        sys.exit(1)
        
    # キーと値がすべて文字列であることを検証
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            print("Error: JSON mapping keys and values must be strings.")
            sys.exit(1)
            
    return data

def load_task_queue(queue_path: Path) -> Dict[str, Any]:
    """task_queue.json ファイルをロードする。ファイルが存在しないか破損している場合はエラー終了。"""
    if not queue_path.exists():
        print(f"Error: Queue path not found: {queue_path}")
        sys.exit(1)
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Task queue file is corrupted or not a valid JSON. {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Error: Failed to read task queue file. {e}")
        sys.exit(1)
        
    if not isinstance(data, dict):
        print("Error: Task queue content must be a JSON dictionary object.")
        sys.exit(1)
        
    if "tasks" not in data:
        print("Error: Task queue is missing required 'tasks' key.")
        sys.exit(1)
        
    if not isinstance(data["tasks"], list):
        print("Error: 'tasks' in task queue must be a list.")
        sys.exit(1)
        
    return data

def update_tasks(task_queue: Dict[str, Any], task_to_agent_map: Dict[str, str]) -> Tuple[Dict[str, Any], bool]:
    """キュー内のタスクをマッピングに従って更新し、更新されたキューとフラグを返す。"""
    is_updated = False
    tasks = task_queue.get("tasks", [])
    if not isinstance(tasks, list):
        print("Error: 'tasks' is not a list in the task queue.")
        sys.exit(1)
        
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            print(f"Warning: Task at index {idx} is not a dictionary. Skipping.")
            continue
        task_id = task.get("id")
        if task_id and isinstance(task_id, str) and task_id in task_to_agent_map:
            task["assigned_agent"] = task_to_agent_map[task_id]
            is_updated = True
    return task_queue, is_updated

def save_task_queue(queue_path: Path, task_queue: Dict[str, Any]) -> None:
    """更新されたキューデータを task_queue.json に保存する。"""
    try:
        with open(queue_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(task_queue, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"Error: Failed to save task queue file. {e}")
        sys.exit(1)

def main() -> None:
    task_to_agent_map = parse_arguments(sys.argv)
    queue_data = load_task_queue(DEFAULT_QUEUE_PATH)
    
    updated_queue, is_updated = update_tasks(queue_data, task_to_agent_map)
    
    if is_updated:
        save_task_queue(DEFAULT_QUEUE_PATH, updated_queue)
        print("Successfully updated assigned_agents in task_queue.json")
    else:
        print("No tasks updated")

if __name__ == "__main__":
    main()

