import sys
import os
import json
import argparse

# プロジェクトルートおよび backend ディレクトリを PYTHONPATH に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    parser = argparse.ArgumentParser(description="Mark a task as done in Orchestration Hub.")
    parser.add_argument("json_file", type=str, nargs="?", help="Path to JSON file containing arguments")
    parser.add_argument("--conversation-id", "-id", type=str, help="Conversation ID")
    parser.add_argument("--task-id", type=str, help="Task ID")
    parser.add_argument("--result", type=str, choices=["pass", "fail", "skip", "skipped"], help="Task result")
    parser.add_argument("--message", type=str, default="", help="Task message")
    parser.add_argument("--changed-files", type=str, default="", help="Comma-separated list of changed files")
    parser.add_argument("--error", type=str, default="", help="Task error details")
    
    args = parser.parse_args()
    
    config = {}
    if args.json_file and os.path.exists(args.json_file) and args.json_file.endswith(".json"):
        try:
            with open(args.json_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Failed to read JSON from file {args.json_file}: {e}")
            sys.exit(1)
    else:
        config = {
            "conversation_id": args.conversation_id,
            "task_id": args.task_id,
            "result": args.result,
            "message": args.message,
            "changed_files": args.changed_files,
            "error": args.error
        }
        
    conv_id = config.get("conversation_id")
    task_id = config.get("task_id")
    result = config.get("result")
    msg = config.get("message", "")
    changed_files = config.get("changed_files", "")
    err = config.get("error", "")
    
    if not conv_id or not task_id or not result:
        print("Missing required fields: conversation_id, task_id, and result must be provided.")
        sys.exit(1)
        
    report = {}
    if msg:
        report["message"] = msg
    if changed_files:
        report["changed_files"] = [f.strip() for f in changed_files.split(",") if f.strip()]
    if err:
        report["error"] = err
        
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conv_id)
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク完了マーク
    if result == "skip":
        result = "skipped"
    print(f"Marking task {task_id} as {result}...")
    hub.mark_task_done(task_id, result, report)
    print("Task marked successfully.")
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
