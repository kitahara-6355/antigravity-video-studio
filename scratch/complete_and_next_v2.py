import sys
sys.path.append('.')
sys.path.append('backend')
from backend.agents.orchestration import OrchestrationHub
import json
from pathlib import Path

hub = OrchestrationHub()

# 心拍更新
hub.flash_update_heartbeat()

# ステータスを取得して、全タスク完了していることを確認
status = hub.generate_flash_status()
print(f"Current Batch Status: completed={status['batch_completed']}/{status['batch_total']}, running={status['batch_running']}")

# タスクキューから実際の集計を行う
TASK_QUEUE_PATH = Path("backend/agents/orchestration/task_queue.json")
queue = {}
if TASK_QUEUE_PATH.exists():
    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
        queue = json.load(f)

batch_id = queue.get("current_batch_id")
tasks = queue.get("tasks", [])

passed = sum(1 for t in tasks if t.get("status") == "pass")
failed = sum(1 for t in tasks if t.get("status") == "fail")
skipped = sum(1 for t in tasks if t.get("status") == "skip")
total = len(tasks)

results = {
    "passed": passed,
    "failed": failed,
    "skipped": skipped,
    "total": total
}

print(f"Batch results to submit for {batch_id}: {results}")

if passed + failed + skipped == total and total > 0:
    print("All tasks completed. Submitting batch report...")
    # バッチレポートの提出
    hub.submit_batch_report(batch_id, results)
    print("Batch report submitted.")
    
    # 次のバッチを取得
    # NIGHTモードの batch_size は 12
    state = hub.get_phase_state()
    phase = state.get("current_phase", 27)
    milestone = state.get("current_milestone", "M27.1")
    print(f"Getting next batch for Phase={phase}, Milestone={milestone}...")
    next_batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=12)
    if next_batch:
        print(f"Successfully obtained next batch of size {len(next_batch)}")
        if len(next_batch) > 0:
            first_task_id = next_batch[0].get("id", "")
            if "T-" in first_task_id:
                parts = first_task_id.split("-")
                if len(parts) > 1:
                    print(f"New Batch ID: {parts[1]}")
    else:
        print("No more batches or tasks available.")
else:
    print("Cannot submit batch yet. Some tasks are still running or not marked pass/fail/skip.")
