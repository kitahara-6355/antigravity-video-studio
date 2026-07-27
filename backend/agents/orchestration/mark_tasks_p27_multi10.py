import sys
import os
import json
from pathlib import Path

# Add backend directory to sys.path with absolute paths
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / 'backend') not in sys.path:
    sys.path.insert(0, str(project_root / 'backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    try:
        hub = OrchestrationHub()
        # 会話ID登録
        hub.register_flash_conversation_id("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
        
        # 1. 心拍更新
        hub.flash_update_heartbeat()
        
        # 2. タスク完了のマーク
        
        # T-batch_3f4c3a-test_weaver-000
        hub.mark_task_done(
            "T-batch_3f4c3a-test_weaver-000",
            "pass",
            {
                "subagent_id": "2a387bbf-fac8-400f-a0d8-c952067e6a5b",
                "message": "philosophy_manager.py テストカバレッジ改善タスク完了報告。カバレッジ 94% -> 100% (+6%)",
                "changed_files": ["backend/tests/test_philosophy_manager.py"]
            }
        )
        print("Marked T-batch_3f4c3a-test_weaver-000 as pass.")
        
        # T-batch_3f4c3a-bug_hunter-000
        hub.mark_task_done(
            "T-batch_3f4c3a-bug_hunter-000",
            "pass",
            {
                "subagent_id": "bc2ee7da-e9ba-48ec-acee-3dd79c3616f0",
                "message": "heartbeat_only.py バグ修正タスク完了。引数混入によるテストFAILをargv引数のオプショナル化で修正",
                "changed_files": [
                    "backend/agents/orchestration/heartbeat_only.py",
                    "backend/tests/test_heartbeat_only.py"
                ]
            }
        )
        print("Marked T-batch_3f4c3a-bug_hunter-000 as pass.")
        
        # 3. 最新ステータス表示
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except Exception as e:
        print(f"Error in mark_tasks_p27_multi10: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

