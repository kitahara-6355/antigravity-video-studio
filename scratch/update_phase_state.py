"""Update phase_state.json with latest metrics from flash_reports."""
import json
import pathlib
from datetime import datetime, timezone

base = pathlib.Path(__file__).resolve().parent.parent / "backend" / "agents"
ps_path = base / "memory" / "phase_state.json"
fr_path = base / "orchestration" / "flash_reports.jsonl"
tq_path = base / "orchestration" / "task_queue.json"

ps = json.loads(ps_path.read_text(encoding="utf-8"))

# Count batches and tasks from flash_reports
batch_count = 0
total_pass = 0
total_fail = 0
with open(fr_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            report = json.loads(line.strip())
            batch_count += 1
            res = report.get("results", {})
            total_pass += res.get("passed", 0)
            total_fail += res.get("failed", 0)
        except (json.JSONDecodeError, KeyError):
            continue

total_tasks = total_pass + total_fail
tq = json.loads(tq_path.read_text(encoding="utf-8"))

print("=== phase_state.json 更新 ===")
print(f"last_updated: {ps['last_updated']} -> now")
print(f"flash_batches_completed: {ps['flash_batches_completed']} -> {batch_count}")
print(f"flash_tasks_total: {ps['flash_tasks_total']} -> {total_tasks}")
print(f"flash_tasks_passed: {ps['flash_tasks_passed']} -> {total_pass}")
print(f"flash_tasks_failed: {ps['flash_tasks_failed']} -> {total_fail}")
print(f"last_batch_id: {ps['last_batch_id']} -> {tq['current_batch_id']}")

ps["flash_batches_completed"] = batch_count
ps["flash_tasks_total"] = total_tasks
ps["flash_tasks_passed"] = total_pass
ps["flash_tasks_failed"] = total_fail
ps["last_batch_id"] = tq["current_batch_id"]
ps["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ps_path.write_text(json.dumps(ps, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("\n✅ phase_state.json を更新しました")
