import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main() -> int:
    """タスク完了マークとステータス更新を行うバッチ実行用メイン関数。
    
    OrchestrationHub を初期化し、対象の Flash セッションIDを登録し、
    特定のタスク (refactor-000, thumbnail-000) を完了状態としてマークします。
    
    Returns:
        int: 終了コード (正常終了時は 0, 例外発生時は 1)
    """
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
        
        # 心拍更新
        hub.flash_update_heartbeat()
        
        # refactor-000 完了マーク
        hub.mark_task_done("T-batch_a97ee3-refactor-000", "pass", {
            "message": "agents/orchestration/atomic_io.py のデッドコード除去・関数分割・テスト追加。",
            "changed_files": [
                "backend/agents/orchestration/atomic_io.py",
                "backend/tests/test_atomic_io.py"
            ]
        })

        # thumbnail-000 完了マーク
        hub.mark_task_done("T-batch_a97ee3-thumbnail-000", "pass", {
            "message": "verify_thumbnail_gen.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/agents/council_graph.py",
                "backend/tests/phase2_validator.py"
            ]
        })
        
        print("TASKS_MARKED_DONE")

        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))
        return 0
    except Exception as e:
        print(f"Error executing mark_tasks: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
