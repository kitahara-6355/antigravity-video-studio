import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
        
        # 心拍更新
        hub.flash_update_heartbeat()
        
        # thumbnail-000 完了マーク
        hub.mark_task_done("T-batch_881c02-thumbnail-000", "pass", {
            "message": "branding/analytics_manager.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/branding/analytics_manager.py",
                "backend/tests/test_analytics_manager.py",
                "backend/agents/memory/technical_debt_index.json"
            ]
        })
        
        # バッチ完了報告
        hub.submit_batch_report("batch_881c02", {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        })
        print("BATCH_SUBMITTED")
    
        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))
    except Exception as e:
        sys.stderr.write(f"Error in mark_and_submit_batch4: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
