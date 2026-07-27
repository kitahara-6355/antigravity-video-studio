import sys
import os
import json

# プロジェクトルートと backend ディレクトリを PYTHONPATH に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..", "backend")))

from backend.agents.orchestration import OrchestrationHub

def main():
    my_conv_id = "3ed8fce0-a204-47fd-a220-c27fecf03706"
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id(my_conv_id)
        
        # 1. 心拍更新
        hub.flash_update_heartbeat()
        print("Heartbeat updated.")
        
        # 2. 各タスクのマーク
        
        # refactor-000 (FAIL: 429)
        hub.mark_task_done(
            "T-batch_394f90-refactor-000",
            "fail",
            {
                "subagent_id": "4a2560b1-426b-4dbd-b5e5-9659a37d87c9",
                "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model.",
                "message": "Subagent failed to start due to Gemini API rate limits (429 RESOURCE_EXHAUSTED)."
            }
        )
        print("Marked T-batch_394f90-refactor-000 as fail.")
        
        # 3. 最新ステータス表示
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except Exception as e:
        print(f"Error in flash_runner_step: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
