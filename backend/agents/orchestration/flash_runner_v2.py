import sys
import os
import argparse
import json

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
# backend フォルダもパスに追加（harness などの直接インポート対応）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    parser = argparse.ArgumentParser(description="Flash Session Runner v2")
    parser.add_argument("--heartbeat", action="store_true", help="Update heartbeat")
    parser.add_argument("--get-batch", action="store_true", help="Get next task batch")
    parser.add_argument("--batch-size", type=int, default=12, help="Batch size")
    parser.add_argument("--register-conv", type=str, help="Register Flash conversation ID")
    parser.add_argument("--status", action="store_true", help="Show current flash status")
    parser.add_argument("--mark-task", action="store_true", help="Mark a task as completed")
    parser.add_argument("--task-id", type=str, help="Task ID to mark")
    parser.add_argument("--task-status", type=str, choices=["pass", "fail", "skip"], help="Task status")
    parser.add_argument("--task-report", type=str, help="JSON string or path to JSON file for task report")
    parser.add_argument("--submit-batch", action="store_true", help="Submit batch report")
    parser.add_argument("--batch-id", type=str, help="Batch ID to submit")
    parser.add_argument("--passed", type=int, help="Number of passed tasks")
    parser.add_argument("--failed", type=int, help="Number of failed tasks")
    parser.add_argument("--skipped", type=int, help="Number of skipped tasks")
    parser.add_argument("--total", type=int, help="Total number of tasks")
    parser.add_argument("--session-end", type=str, help="End session with completion message")

    args = parser.parse_args()
    hub = OrchestrationHub()

    if args.register_conv:
        hub.register_flash_conversation_id(args.register_conv)
        print(f"Registered conversation ID: {args.register_conv}")

    if args.heartbeat:
        hub.flash_update_heartbeat()
        print("Heartbeat updated.")
        status = hub.generate_flash_status()
        print("=== CURRENT STATUS ===")
        print(status.get("formatted", ""))
        print("======================")

    elif args.get_batch:
        state = hub.get_phase_state()
        phase = state.get("current_phase", 27)
        milestone = state.get("current_milestone", "M27.1")
        batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=args.batch_size)
        print(json.dumps(batch, indent=2, ensure_ascii=False))

    elif args.status:
        status = hub.generate_flash_status()
        print("=== CURRENT STATUS ===")
        print(status.get("formatted", ""))
        print("======================")

    elif args.mark_task:
        if not args.task_id or not args.task_status:
            print("Error: --task-id and --task-status are required for --mark-task")
            sys.exit(1)
        
        report = {}
        if args.task_report:
            if os.path.exists(args.task_report):
                with open(args.task_report, "r", encoding="utf-8") as f:
                    report = json.load(f)
            else:
                try:
                    report = json.loads(args.task_report)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse task report as JSON, treating as raw message: {e}")
                    report = {"message": args.task_report}
        
        hub.mark_task_done(args.task_id, args.task_status, report)
        print(f"Task {args.task_id} marked as {args.task_status}.")

    elif args.submit_batch:
        if not args.batch_id or args.passed is None or args.failed is None or args.skipped is None or args.total is None:
            print("Error: --batch-id, --passed, --failed, --skipped, and --total are required for --submit-batch")
            sys.exit(1)
        
        results = {
            "passed": args.passed,
            "failed": args.failed,
            "skipped": args.skipped,
            "total": args.total
        }
        hub.submit_batch_report(args.batch_id, results)
        print(f"Batch {args.batch_id} submitted with results: {results}")

    elif args.session_end:
        hub.flash_session_end(args.session_end)
        print(f"Session ended with message: {args.session_end}")

if __name__ == "__main__":
    main()
