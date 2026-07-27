import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

queue_path = PROJECT_ROOT / "backend/agents/orchestration/task_queue.json"

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

updated = False
for task in queue.get("tasks", []):
    if task["id"] == "T-batch_501cdc-thumbnail-000" and task["status"] == "running":
        task["status"] = "pass"
        task["result"] = {
            "changed_files": ["comprehensive_preview.py"]
        }
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        updated = True
        print(f"Marked task {task['id']} as pass.")
        break

if updated:
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
