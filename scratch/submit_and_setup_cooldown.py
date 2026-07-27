import sys
sys.path.append('.')
sys.path.append('backend')
from backend.agents.orchestration import OrchestrationHub
import json
import time
from pathlib import Path

def main():
    hub = OrchestrationHub()

    # 心拍更新
    hub.flash_update_heartbeat()

    # タスクキューから集計を行う
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
        print("Submitting batch report...")
        hub.submit_batch_report(batch_id, results)
        print("Batch report submitted.")
        
        # 次のバッチを取得
        state = hub.get_phase_state()
        phase = state.get("current_phase", 27)
        milestone = state.get("current_milestone", "M27.1")
        print(f"Getting next batch for Phase={phase}, Milestone={milestone}...")
        next_batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
        if next_batch:
            print(f"Successfully obtained next batch of size {len(next_batch)}")
        else:
            print("No more batches or tasks available.")
            
        # クールダウン状態の書き出し
        # 1時間39分(5940秒) + 安全マージン = 6200秒
        current_time = time.time()
        reset_timestamp = current_time + 6200
        cooldown_data = {
            "cooldown_active": True,
            "reset_timestamp": reset_timestamp,
            "reset_time_str": time.strftime("%Y-%m-%d %H:%M:%S JST", time.localtime(reset_timestamp))
        }
        
        cooldown_path = Path("scratch/cooldown_state.json")
        with open(cooldown_path, "w", encoding="utf-8") as f:
            json.dump(cooldown_data, f, ensure_ascii=False, indent=2)
        print(f"Cooldown state saved. Reset time set to: {cooldown_data['reset_time_str']}")
        
    else:
        print("Cannot submit batch yet. Some tasks are still running or not marked pass/fail/skip.")

if __name__ == "__main__":
    main()
