import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 2. mark_task_done
    task_id = "T-batch_f08054-thumbnail-003"
    result_status = "pass"
    report = {
        "message": "routers/websocket.py のテストカバレッジを100%に達成。Pydantic v2ワークアラウンドをテストに追加し、計10テストでPASSしました。",
        "changed_files": ["backend/tests/test_websocket.py"]
    }
    hub.mark_task_done(task_id, result_status, report)
    print("Task marked as done.")
    
    # 3. submit_batch_report (6件PASS)
    batch_id = "batch_f08054"
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
