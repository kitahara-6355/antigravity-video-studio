import sys
import argparse
import json
from typing import List, Dict, Any, Optional

# プロジェクトルートの追加
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.atomic_io import safe_read_json

DEFAULT_CONVERSATION_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"
DEFAULT_TASKS = [
    {
        "task_id": "T-batch_a1eb03-test_weaver-000",
        "status": "pass",
        "result": {
            "message": "branding_manager.py のテスト追加。カバレッジ 0% -> 99% へ向上。",
            "changed_files": ["tests/test_branding_manager.py"]
        }
    },
    {
        "task_id": "T-batch_a1eb03-thumbnail-000",
        "status": "pass",
        "result": {
            "message": "agents/strategist.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/agents/strategist.py",
                "backend/agents/council_graph.py",
                "backend/usage_tracker/alert_system.py"
            ]
        }
    }
]

def check_task_exists(task_id: str) -> bool:
    """タスクIDが task_queue.json に存在するかどうかを確認する"""
    from pathlib import Path
    queue_path = Path(__file__).resolve().parent / "task_queue.json"
    data = safe_read_json(str(queue_path), default=None)
    if not data:
        return False
    try:
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            return False
        return any(t.get("id") == task_id for t in tasks if isinstance(t, dict))
    except (TypeError, AttributeError):
        return False

def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする"""
    parser = argparse.ArgumentParser(description="Flashタスクを完了マークするスクリプト")
    parser.add_argument("--conversation-id", type=str, default=DEFAULT_CONVERSATION_ID,
                        help="対象のFlash Conversation ID")
    parser.add_argument("--task-id", type=str, help="完了マークするタスクID")
    parser.add_argument("--status", type=str, default="pass", help="タスクのステータス (pass/fail)")
    parser.add_argument("--message", type=str, help="タスクの完了メッセージ")
    parser.add_argument("--changed-files", type=str, nargs="*", help="変更したファイルの一覧")
    return parser.parse_args()

def initialize_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、Conversation IDを登録する"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub

def mark_single_task(hub: OrchestrationHub, task_id: str, status: str, task_result: Dict[str, Any]) -> None:
    """単一のタスクを完了マークする"""
    hub.mark_task_done(task_id, status, task_result)

def mark_multiple_tasks(hub: OrchestrationHub, tasks: List[Dict[str, Any]]) -> None:
    """複数のタスクを完了マークする"""
    for task in tasks:
        mark_single_task(hub, task["task_id"], task["status"], task["result"])
    print("TASKS_MARKED_DONE")

def print_status(hub: OrchestrationHub) -> None:
    """最新ステータスを表示する"""
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

def execute_single_task_marking(
    hub: OrchestrationHub,
    task_id: str,
    status: str,
    message: Optional[str],
    changed_files: Optional[List[str]]
) -> None:
    """単一タスクの完了処理を組み立てて実行する"""
    task_result = {
        "message": message or "",
        "changed_files": changed_files or []
    }
    mark_single_task(hub, task_id, status, task_result)
    print("TASKS_MARKED_DONE")

def execute_multiple_tasks_marking(hub: OrchestrationHub, tasks: List[Dict[str, Any]]) -> None:
    """複数タスクの完了処理を実行する"""
    mark_multiple_tasks(hub, tasks)

def main() -> None:
    try:
        args = parse_args()
        
        # ステータスのバリデーション
        if args.status not in ("pass", "fail"):
            sys.stderr.write(f"エラー: 無効なステータス '{args.status}'。'pass' または 'fail' を指定してください。\n")
            sys.exit(1)
            
        hub = initialize_hub(args.conversation_id)
        
        if args.task_id:
            if not check_task_exists(args.task_id):
                sys.stderr.write(f"エラー: 指定されたタスクID '{args.task_id}' はタスクキューに存在しません。\n")
                sys.exit(1)
            execute_single_task_marking(
                hub=hub,
                task_id=args.task_id,
                status=args.status,
                message=args.message,
                changed_files=args.changed_files
            )
        else:
            for task in DEFAULT_TASKS:
                if not check_task_exists(task["task_id"]):
                    sys.stderr.write(f"警告: デフォルトタスク '{task['task_id']}' はタスクキューに存在しません。\n")
            execute_multiple_tasks_marking(hub, DEFAULT_TASKS)
            
        print_status(hub)
    except (ValueError, KeyError, OSError, json.JSONDecodeError, AttributeError) as e:
        sys.stderr.write(f"エラー: 実行中にエラーが発生しました: {str(e)}\n")
        sys.exit(1)
    except (TypeError, IndexError, RuntimeError, ImportError) as e:
        sys.stderr.write(f"エラー: 予期せぬシステムエラーが発生しました: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()