import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # thumbnail-001 完了マーク
    hub.mark_task_done("T-batch_214e16-thumbnail-001", "pass", {
        "message": "harness/evaluator_optimizer.py のサムネイル処理改善と品質検証・テスト追加。",
        "changed_files": [
            "backend/harness/evaluator_optimizer.py",
            "tests/test_evaluator_optimizer.py"
        ]
    })

    # bug_hunter-000 完了マーク
    hub.mark_task_done("T-batch_214e16-bug_hunter-000", "pass", {
        "message": "graded_previews/nhk_subtitle_scorer.py の例外処理保護とテスト追加。",
        "changed_files": [
            "backend/graded_previews/nhk_subtitle_scorer.py",
            "backend/tests/test_nhk_subtitle_scorer.py"
        ]
    })
    
    # バッチ完了報告
    hub.submit_batch_report("batch_214e16", {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6,
    })
    print("BATCH_SUBMITTED")
    
    print("TASKS_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
