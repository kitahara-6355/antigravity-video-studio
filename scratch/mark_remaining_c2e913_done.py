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

completed_ids = {
    "T-batch_c2e913-thumbnail-000": ["backend/comprehensive_preview.py"],
    "T-batch_c2e913-refactor-000": ["backend/tests/e2e_stability.py"]
}

updated = False
for task in queue.get("tasks", []):
    if task["id"] in completed_ids and task["status"] == "running":
        task["status"] = "pass"
        task["result"] = {
            "changed_files": completed_ids[task["id"]]
        }
        task["completed_at"] = datetime.utcnow().isoformat() + "Z"
        updated = True
        print(f"Marked task {task['id']} as pass.")

if updated:
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
