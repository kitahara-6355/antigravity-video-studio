# -*- coding: utf-8 -*-
import json
import os

def _resolve_file_path(root_path, provided_path, relative_subpath, fallback_absolute_path):
    """
    指定されたパスを解決します。
    provided_path が指定されている場合はそれを優先し、
    未指定の場合は root_path からの相対パス、それが存在しない場合は fallback パスを使用します。
    """
    if provided_path is not None:
        return provided_path
    
    primary_path = os.path.join(root_path, relative_subpath)
    if os.path.exists(primary_path):
        return primary_path
        
    if os.path.exists(fallback_absolute_path):
        return fallback_absolute_path
        
    return primary_path

def _print_phase_state(phase_path):
    """Phase Stateの情報を読み込んで出力します。"""
    print("=== Phase State ===")
    if os.path.exists(phase_path):
        try:
            with open(phase_path, "r", encoding="utf-8") as f:
                state = json.load(f)
                print(f"Current Phase: {state.get('current_phase')}")
                print(f"Current Milestone: {state.get('current_milestone')}")
                print(f"Last Batch ID (Phase State): {state.get('last_batch_id')}")
                print(f"Total: {state.get('flash_tasks_total')}, Passed: {state.get('flash_tasks_passed')}, Failed: {state.get('flash_tasks_failed')}")
        except json.JSONDecodeError as e:
            print(f"Error parsing phase state JSON: {e}")
        except OSError as e:
            print(f"Error reading phase state file: {e}")
    else:
        print("No phase state found.")

def _print_session_state(session_path):
    """Session Stateの情報を読み込んで出力します。"""
    print("\n=== Session State ===")
    if os.path.exists(session_path):
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                session_data = json.load(f)
                print(f"Consecutive Failures: {session_data.get('consecutive_failures', 0)}")
                recent_errors = session_data.get('recent_errors', [])
                print(f"Recent Errors Count: {len(recent_errors)}")
                if recent_errors:
                    print("Recent Errors:")
                    for err in recent_errors:
                        print(f"  - {err}")
        except json.JSONDecodeError as e:
            print(f"Error parsing session state JSON: {e}")
        except OSError as e:
            print(f"Error reading session state file: {e}")
    else:
        print("No session state found.")

def _print_task_queue(queue_path):
    """Task Queueの情報を読み込んで出力します。"""
    print("\n=== Task Queue ===")
    if os.path.exists(queue_path):
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                queue_data = json.load(f)
                current_batch_id = queue_data.get("current_batch_id")
                print(f"Current Batch ID in Queue: {current_batch_id}")
                tasks = queue_data.get("tasks", [])
                print(f"Total tasks in queue: {len(tasks)}")
                
                # Group by status
                by_status = {}
                for t in tasks:
                    status = t.get("status")
                    by_status[status] = by_status.get(status, 0) + 1
                print(f"Status summary: {by_status}")
                
                # Show details of all tasks
                print("\nAll Tasks in Queue:")
                for t in tasks:
                    print(f"  - ID: {t.get('id')} | Group: {t.get('group')} | Target: {t.get('target_module')} | Status: {t.get('status')} | Agent: {t.get('assigned_agent')}")
        except json.JSONDecodeError as e:
            print(f"Error parsing task queue JSON: {e}")
        except OSError as e:
            print(f"Error reading task queue file: {e}")
    else:
        print("No task queue found.")

def check(queue_path=None, session_path=None, phase_path=None):
    """
    フェーズ状態、セッション状態、タスクキューの状況を確認し、標準出力に表示します。
    """
    # Dynamic root path resolution
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    root_path = os.environ.get("VIDEO_AUTOMATION_ROOT", default_root)

    # パスの解決
    phase_path = _resolve_file_path(
        root_path, 
        phase_path, 
        os.path.join("backend", "agents", "memory", "phase_state.json"),
        r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\phase_state.json"
    )
    
    queue_path = _resolve_file_path(
        root_path,
        queue_path,
        os.path.join("backend", "agents", "orchestration", "task_queue.json"),
        r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\task_queue.json"
    )
    
    session_path = _resolve_file_path(
        root_path,
        session_path,
        os.path.join("backend", "agents", "orchestration", "flash_session.json"),
        r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\flash_session.json"
    )

    # 各状態の出力
    _print_phase_state(phase_path)
    _print_session_state(session_path)
    _print_task_queue(queue_path)

if __name__ == "__main__":
    check()
