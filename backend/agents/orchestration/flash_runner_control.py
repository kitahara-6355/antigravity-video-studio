import sys
import os
import argparse
import json

# プロジェクトルートを PYTHONPATH に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..", "backend")))

from backend.agents.orchestration import OrchestrationHub

def main():
    parser = argparse.ArgumentParser(description="Flash Session Controller")
    parser.add_argument("--conversation-id", "-id", type=str, required=True, help="Conversation ID")
    parser.add_argument("--get-batch", action="store_true", help="Get next task batch")
    parser.add_argument("--batch-size", type=int, default=6, help="Batch size")
    parser.add_argument("--phase", type=int, help="Optional phase number")
    parser.add_argument("--milestone", type=str, help="Optional milestone name")
    parser.add_argument("--mark-task", action="store_true", help="Mark a task as completed")
    parser.add_argument("--task-id", type=str, help="Task ID")
    parser.add_argument("--task-status", type=str, choices=["pass", "fail", "skip"], help="Task status")
    parser.add_argument("--task-report", type=str, help="JSON or path or message")
    parser.add_argument("--submit-batch", action="store_true", help="Submit batch report")
    parser.add_argument("--batch-id", type=str, help="Batch ID")
    parser.add_argument("--passed", type=int, help="Passed tasks count")
    parser.add_argument("--failed", type=int, help="Failed tasks count")
    parser.add_argument("--skipped", type=int, help="Skipped tasks count")
    parser.add_argument("--total", type=int, help="Total tasks count")
    parser.add_argument("--session-end", type=str, help="End session message")
    
    args = parser.parse_args()
    hub = OrchestrationHub()
    
    # 心拍更新を常に最初に行う (心拍レジリエンス規約)
    hub.register_flash_conversation_id(args.conversation_id)
    hub.flash_update_heartbeat()
    
    if args.get_batch:
        phase = args.phase
        milestone = args.milestone
        if not phase or not milestone:
            state = hub.get_phase_state()
            phase = state.get("current_phase", 33)
            milestone = state.get("current_milestone", "M33.1")
        batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=args.batch_size)
        print("=== BATCH ===")
        print(json.dumps(batch, indent=2, ensure_ascii=False))
        print("=============")
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status.get("formatted", ""))
        print("==============")
        
    elif args.mark_task:
        if not args.task_id or not args.task_status:
            print("Error: --task-id and --task-status required", file=sys.stderr)
            sys.exit(1)
        report = {}
        if args.task_report:
            if os.path.exists(args.task_report):
                try:
                    with open(args.task_report, "r", encoding="utf-8") as f:
                        report = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    print(f"Error: Failed to load report from file '{args.task_report}': {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                try:
                    report = json.loads(args.task_report)
                except json.JSONDecodeError:
                    report = {"message": args.task_report}
        hub.mark_task_done(args.task_id, args.task_status, report)
        print(f"Task {args.task_id} marked as {args.task_status}")
        
    elif args.submit_batch:
        if not args.batch_id or args.passed is None or args.failed is None or args.skipped is None or args.total is None:
            print("Error: --batch-id, --passed, --failed, --skipped, --total required", file=sys.stderr)
            sys.exit(1)
        if args.passed < 0 or args.failed < 0 or args.skipped < 0 or args.total < 0:
            print("Error: Task counts cannot be negative", file=sys.stderr)
            sys.exit(1)
        if args.passed + args.failed + args.skipped != args.total:
            print(f"Error: Sum of passed ({args.passed}), failed ({args.failed}), and skipped ({args.skipped}) must equal total ({args.total})", file=sys.stderr)
            sys.exit(1)
        results = {
            "passed": args.passed,
            "failed": args.failed,
            "skipped": args.skipped,
            "total": args.total
        }
        hub.submit_batch_report(args.batch_id, results)
        print(f"Batch {args.batch_id} submitted")
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status.get("formatted", ""))
        print("==============")
        
    elif args.session_end is not None:
        hub.flash_session_end(args.session_end)
        print(f"Session ended: {args.session_end}")
        
    else:
        print("Error: No action specified. Specify one of --get-batch, --mark-task, --submit-batch, or --session-end.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
