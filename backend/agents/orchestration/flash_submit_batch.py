import sys
import os
import json
import argparse

"""Submit a batch report to Orchestration Hub.

This module aggregates the execution results of subagent tasks from the
task queue file and reports the summary (passed, failed, skipped) to the
Orchestration Hub. It also updates the heartbeats and retrieves the current status.
"""

# プロジェクトルートおよび backend ディレクトリを PYTHONPATH に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    """Main execution function to submit batch reports to Orchestration Hub.
    
    Parses arguments, resolves conversation ID, aggregates task statuses from 
    task_queue.json, submits the report, and displays the current flash status.
    """
    parser = argparse.ArgumentParser(description="Submit a batch report to Orchestration Hub.")
    parser.add_argument("--conversation-id", "-id", type=str, help="Conversation ID")
    args = parser.parse_args()
    
    hub = OrchestrationHub()
    
    # Conversation ID の解決
    conv_id = args.conversation_id
    if not conv_id:
        conv_id = os.environ.get("FLASH_CONVERSATION_ID") or os.environ.get("CONVERSATION_ID")
        
    if not conv_id:
        try:
            session = hub.get_flash_session()
            conv_id = session.get("conversation_id") if isinstance(session, dict) else None
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            pass
            
    if not conv_id:
        conv_id = "846cd96f-9aaa-41f7-b29e-ece50b846de9"
        
    hub.register_flash_conversation_id(conv_id)
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. task_queue.json から結果を集計
    queue_path = "backend/agents/orchestration/task_queue.json"
    if not os.path.exists(queue_path):
        print(f"Error: {queue_path} not found.", file=sys.stderr)
        sys.exit(1)
        
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            queue_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading or parsing {queue_path}: {e}", file=sys.stderr)
        sys.exit(1)
        
    batch_id = queue_data.get("current_batch_id")
    tasks = queue_data.get("tasks", [])
    
    passed = 0
    failed = 0
    skipped = 0
    
    for task in tasks:
        status = task.get("status")
        if status == "pass":
            passed += 1
        elif status == "fail":
            failed += 1
        elif status in ("skip", "skipped"):
            skipped += 1
            
    total = len(tasks)
    
    print(f"Submitting batch {batch_id}: passed={passed}, failed={failed}, skipped={skipped}, total={total}")
    
    # 3. 報告の送信
    hub.submit_batch_report(batch_id, {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": total
    })
    
    # 4. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":  # pragma: no cover
    main()
