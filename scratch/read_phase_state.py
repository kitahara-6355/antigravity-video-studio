"""Read phase_state.json and print key metrics."""
import json, pathlib

ps_path = pathlib.Path(__file__).resolve().parent.parent / "backend" / "agents" / "memory" / "phase_state.json"
ps = json.loads(ps_path.read_text(encoding="utf-8"))

print(f"last_updated: {ps['last_updated']}")
print(f"flash_batches_completed: {ps['flash_batches_completed']}")
print(f"flash_tasks_total: {ps['flash_tasks_total']}")
print(f"flash_tasks_passed: {ps['flash_tasks_passed']}")
print(f"flash_tasks_failed: {ps['flash_tasks_failed']}")
print(f"test_count: {ps['metrics']['test_count']}")
print(f"coverage_pct: {ps['metrics']['coverage_pct']}")
print(f"ratchet_items: {ps['metrics']['ratchet_items']}")
print(f"critical_debt: {ps['metrics']['critical_debt']}")
