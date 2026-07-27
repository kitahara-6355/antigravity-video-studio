import json
import os

reports_path = "backend/agents/orchestration/flash_reports.jsonl"
if os.path.exists(reports_path):
    print(f"Reports path size: {os.path.getsize(reports_path)} bytes")
    with open(reports_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    # Read last 10 lines
    for i in range(max(0, len(lines)-10), len(lines)):
        try:
            report = json.loads(lines[i])
            print(f"Index {i} | Time: {report.get('timestamp')} | Event: {report.get('event')} | Batch: {report.get('batch_id')}")
            # If tasks, print summary
            if "tasks" in report:
                print(f"  Tasks count: {len(report['tasks'])}")
            if "status" in report:
                print(f"  Status: {report['status']}")
        except Exception as e:
            print(f"Error parsing report line {i}: {e}")
else:
    print("Reports file does not exist")
