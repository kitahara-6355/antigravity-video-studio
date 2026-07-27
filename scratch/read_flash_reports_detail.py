import json
import os

reports_path = "backend/agents/orchestration/flash_reports.jsonl"
if os.path.exists(reports_path):
    with open(reports_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Check the last 5 reports
    for i in range(max(0, len(lines)-5), len(lines)):
        try:
            report = json.loads(lines[i])
            print(f"\n--- REPORT INDEX {i} ---")
            print(f"Timestamp: {report.get('timestamp')}")
            print(f"Batch ID: {report.get('batch_id')}")
            print(f"Status: {report.get('status')}")
            tasks = report.get("tasks", [])
            print(f"Tasks: {len(tasks)}")
            for t in tasks:
                print(f"  - ID: {t.get('id')} | Module: {t.get('target_module')} | Status: {t.get('status')}")
        except Exception as e:
            print(f"Error parsing line {i}: {e}")
else:
    print("Reports file does not exist")
