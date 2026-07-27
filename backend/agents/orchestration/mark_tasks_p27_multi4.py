import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # refactor-000 完了マーク
    hub.mark_task_done("T-batch_881c02-refactor-000", "pass", {
        "message": "integration_test.py のデッドコード除去・関数分割・テストバグ修正。",
        "changed_files": [
            "backend/integration_test.py",
            "backend/tests/test_scratch_integration_test.py"
        ]
    })

    # thumbnail-001 完了マーク
    hub.mark_task_done("T-batch_881c02-thumbnail-001", "pass", {
        "message": "routers/segments.py におけるサムネイル生成API（/segments/thumbnail）の追加、および自動リトライ動作のテスト追加。",
        "changed_files": [
            "backend/routers/segments.py",
            "backend/agents/council_graph.py",
            "backend/tests/test_segments_thumbnail.py"
        ]
    })
    
    print("TASKS_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
