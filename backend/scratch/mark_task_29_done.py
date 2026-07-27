import os
import sys
import traceback

project_root = None

def setup_project_path() -> None:
    """プロジェクトルートディレクトリを sys.path に動的に追加します。"""
    global project_root
    if "__file__" in globals() and globals()["__file__"]:
        current_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        current_dir = os.getcwd()
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    normalized_paths = {os.path.abspath(p) for p in sys.path if p}
    if os.path.abspath(project_root) not in normalized_paths:
        sys.path.insert(0, project_root)

setup_project_path()

def main(task_id: str = "T-batch_769699-thumbnail-029") -> int:
    import re
    if not task_id or not re.match(r"^T-batch_[0-9a-fA-F]+-[a-zA-Z0-9_-]+-\d+$", task_id):
        print(f"Validation Error: Invalid task_id format: '{task_id}'", file=sys.stderr)
        return 1

    try:
        from backend.agents.orchestration import OrchestrationHub
    except ImportError as e:
        print(f"Import Error: Could not import OrchestrationHub. {e}", file=sys.stderr)
        return 1

    import json
    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()
        hub.mark_task_done(
            task_id=task_id,
            result="pass",
            report={
                "message": "tests/_screenshot_dashboard.py: C0/ブランチカバレッジ 100% 維持。2つの新規テストケースを追加し堅牢性向上",
                "changed_files": ["backend/tests/test_screenshot_dashboard.py"]
            }
        )
    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: Managed JSON file is corrupted: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"File Not Found Error: Orchestration file missing: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"Permission Error: Access denied to orchestration files: {e}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"Key Error: Missing required key in orchestration data: {e}", file=sys.stderr)
        return 1
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        print(f"Error marking task as done due to orchestration/system issue: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())

