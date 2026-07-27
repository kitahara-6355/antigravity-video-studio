import sys
import os
import json

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)
sys.path.insert(0, os.path.join(base_dir, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    # CWDを video-automation に固定
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(base_dir)
    sys.path.append(os.path.join(base_dir, "backend"))
    
    hub = OrchestrationHub()
    # 0. 心拍更新
    hub.flash_update_heartbeat()
    
    # 現在のキュー状態を取得
    state = hub.get_phase_state()
    queue_status = hub.get_queue_status()
    
    phase = state.get("current_phase", 27)
    milestone = state.get("current_milestone", "M27.1")
    
    # 現在のバッチIDとタスク
    batch_id = queue_status.get("batch_id")
    
    # task_queue.json を直接読み込んで、現在のバッチ内のタスク状態を確認
    queue_path = os.path.join("backend", "agents", "orchestration", "task_queue.json")
    
    tasks = []
    if os.path.exists(queue_path):
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                queue_data = json.load(f)
                tasks = queue_data.get("tasks", [])
        except Exception as e:
            print(json.dumps({"error": f"Failed to read task queue: {e}"}))
            return

    # バッチ内のタスクで status が "pending" または "running" のものをカウント
    pending_or_running = [t for t in tasks if t.get("status") in ("pending", "running")]
    
    # バッチ完了判定
    if batch_id and len(tasks) > 0 and len(pending_or_running) == 0:
        # 全てのタスクが完了（pass, fail, skip）している場合、バッチ報告を送信
        passed = len([t for t in tasks if t.get("status") == "pass"])
        failed = len([t for t in tasks if t.get("status") == "fail"])
        skipped = len([t for t in tasks if t.get("status") == "skip"])
        
        hub.submit_batch_report(batch_id, {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": len(tasks)
        })
        print(f"Batch {batch_id} completed and submitted. (passed={passed}, failed={failed}, skipped={skipped})")
        # 状態を再ロードするため、バッチIDなどをクリア
        batch_id = None
        tasks = []

    # バッチIDがない（または今完了した）場合、新しいバッチを取得
    if not batch_id or len(tasks) == 0:
        # 動作モードWEEKENDにより、MAX_PARALLEL=10
        next_tasks = hub.get_next_batch(phase, milestone, batch_size=10)
        if not next_tasks:
            print(json.dumps({"action": "idle", "message": "No pending tasks. Phase might be complete or awaiting review."}))
            return
        
        # 新しいバッチIDを再取得
        queue_status = hub.get_queue_status()
        batch_id = queue_status.get("batch_id")
        
        # 出力
        print(json.dumps({
            "action": "dispatch",
            "batch_id": batch_id,
            "tasks": next_tasks
        }, indent=2))
        return

    # 現在のバッチが実行中の場合はステータスを出力
    status = hub.generate_flash_status()
    print(json.dumps({
        "action": "status",
        "batch_id": batch_id,
        "status_summary": status.get("formatted", ""),
        "context_consumption_pct": status.get("context_consumption_pct", 0),
        "archive_urgency": status.get("archive_urgency", "normal"),
        "running_tasks": [t["id"] for t in pending_or_running]
    }, indent=2))

if __name__ == "__main__":
    main()
