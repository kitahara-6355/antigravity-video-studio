import sys
import os

# python path の設定
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    
    # キューのステータスを取得
    status = hub.get_queue_status()
    print("=== Queue Status ===")
    print(json.dumps(status, indent=2))
    
    # バッチ内のタスクを集計
    # 実際にはhub内で_read_jsonはヘルパー関数なので、直接読み取る
    queue_path = "backend/agents/orchestration/task_queue.json"
    with open(queue_path, "r", encoding="utf-8") as f:
        queue = json.load(f)
    
    tasks = queue.get("tasks", [])
    batch_id = queue.get("current_batch_id")
    
    completed = sum(1 for t in tasks if t.get("status") in ("pass", "fail", "skip"))
    passed = sum(1 for t in tasks if t.get("status") == "pass")
    failed = sum(1 for t in tasks if t.get("status") == "fail")
    skipped = sum(1 for t in tasks if t.get("status") == "skip")
    total = len(tasks)
    
    print(f"Batch {batch_id}: {completed}/{total} completed (pass={passed}, fail={failed}, skip={skipped})")
    
    # もし全タスクが完了していれば、レポートを送信
    if total > 0 and completed == total:
        print(f"Submitting batch report for {batch_id}...")
        hub.submit_batch_report(batch_id, {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total
        })
        # 送信後に再読み込み
        with open(queue_path, "r", encoding="utf-8") as f:
            queue = json.load(f)
        batch_id = queue.get("current_batch_id")
        print(f"Submitted. New batch ID is {batch_id}")
    
    # 次のバッチを取得（Phase 26 / Milestone M26.1）
    # get_next_batch を呼んで新バッチを取得
    print("Calling get_next_batch...")
    batch = hub.get_next_batch(phase=26, milestone="M26.1", batch_size=6)
    print(f"Got next batch of size: {len(batch)}")
    for t in batch:
        print(f"  Task: {t.get('id')} - {t.get('target_module')} - status: {t.get('status')}")
    
    # 最新のステータスを表示
    flash_status = hub.generate_flash_status()
    print("=== Flash Status Formatted ===")
    print(flash_status.get("formatted", "No formatted status available"))
    
if __name__ == "__main__":
    main()
