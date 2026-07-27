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
    
    # 1. タスク T-batch_d93914-bug_hunter-000 を pass にマーク
    hub.mark_task_done(
        "T-batch_d93914-bug_hunter-000",
        "pass",
        {
            "message": "self_healing_tool.py 内の except Exception (3箇所) を具体的な例外（ArithmeticError, AttributeError, OSError, SubprocessError 等）に置換。安全弁で RuntimeError などの例外が発生した場合の例外安全を強化。ユニットテストを追加し 100% PASS を確認。",
            "changed_files": [
                "backend/agents/self_healing_tool.py",
                "backend/tests/test_self_healing_tool.py"
            ]
        }
    )
    print("Task T-batch_d93914-bug_hunter-000 marked as pass.")

if __name__ == "__main__":
    main()
