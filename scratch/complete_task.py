import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 2. mark_task_done
    task_id = "T-batch_af13da-thumbnail-002"
    result_status = "pass"
    report = {
        "message": "routers/admin_analytics_router.py のカバレッジ100%達成を検証。既存テスト（30件）で全PASSしカバレッジ100%であることを確認。",
        "changed_files": []
    }
    hub.mark_task_done(task_id, result_status, report)
    print("Task marked as done.")
    
    # 3. submit_batch_report
    # バッチ全体の情報を集計して報告
    # 5件PASS + 今回1件PASS = 6件PASS
    batch_id = "batch_af13da"
    hub.submit_batch_report(batch_id, {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })
    print("Batch report submitted.")
    
    # 4. generate_flash_status
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status.get("formatted", ""))
    print("=== END ===")

if __name__ == "__main__":
    main()
