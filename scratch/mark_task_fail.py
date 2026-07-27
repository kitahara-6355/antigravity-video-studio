import sys
import os

# プロジェクトルートと backend を PYTHONPATH に追加
project_root = r"c:\Users\PC_User\Desktop\script\video-automation"
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 0. 心拍更新
    hub.flash_update_heartbeat()
    
    # 1. タスク T-batch_d93914-bug_hunter-000 を fail にマーク
    hub.mark_task_done(
        "T-batch_d93914-bug_hunter-000",
        "fail",
        {
            "message": "bug_hunter Agent 0 timed out after 600 seconds during fitness function verification. Killing subagent and marking task as fail.",
            "changed_files": []
        }
    )
    print("Task T-batch_d93914-bug_hunter-000 marked as fail.")

if __name__ == "__main__":
    main()
