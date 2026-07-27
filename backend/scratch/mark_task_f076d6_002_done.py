import sys
sys.path.insert(0, "C:/Users/PC_User/Desktop/script/video-automation")
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
hub.flash_update_heartbeat()
hub.mark_task_done(
    task_id="T-batch_f076d6-thumbnail-002",
    result="pass",
    report={
        "message": "verify_full_system.py: カバレッジ 100% 達成。debate_flow や synthesis が None の場合のテストを追加",
        "changed_files": ["backend/tests/test_verify_full_system.py"]
    }
)
