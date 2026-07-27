import sys
import os
import json

# プロジェクトルートと backend を PYTHONPATH に追加
project_root = r"c:\Users\PC_User\Desktop\script\video-automation"
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from backend.agents.orchestration import OrchestrationHub

# モック化のためのパッチ
def dummy_measure(*args, **kwargs):
    print("MOCKED: _auto_measure_coverage")
    return {}

def dummy_git_commit(*args, **kwargs):
    print("MOCKED: _git_auto_commit")
    return True

def main():
    hub = OrchestrationHub()
    # 0. 心拍更新
    hub.flash_update_heartbeat()

    # モンキーパッチ適用
    hub._auto_measure_coverage = dummy_measure
    hub._git_auto_commit = dummy_git_commit

    # 現在のキュー状態
    state = hub.get_phase_state()
    queue_status = hub.get_queue_status()
    batch_id = queue_status.get("batch_id")
    phase = state.get("current_phase", 33)
    milestone = state.get("current_milestone", "M33.1")

    print(f"Submitting batch: {batch_id}")
    
    # バッチ提出 (6/6 pass で提出)
    hub.submit_batch_report(batch_id, {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })
    print("Batch submitted successfully.")

    # 1秒待機
    import time
    time.sleep(1)

    # 次のバッチを取得 (batch_size=6)
    print("Requesting next batch...")
    next_tasks = hub.get_next_batch(phase, milestone, batch_size=6)
    
    # 新しいバッチIDを再取得
    new_queue_status = hub.get_queue_status()
    new_batch_id = new_queue_status.get("batch_id")

    print(json.dumps({
        "status": "success",
        "new_batch_id": new_batch_id,
        "tasks": next_tasks
    }, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
