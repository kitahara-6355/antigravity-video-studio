import sys
sys.path.append('.')
sys.path.append('backend')
import subprocess
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
hub.flash_update_heartbeat()

tasks = [
    {
        "id": "T-batch_6a3e42-tdr_cleanup-000",
        "cmd": ["pytest", "backend/tests/test_token_limiter.py", "--timeout=300"]
    },
    {
        "id": "T-batch_6a3e42-thumbnail-002",
        "cmd": ["pytest", "backend/tests/test_verify_thumbnail_gen.py", "--timeout=300"]
    },
    {
        "id": "T-batch_6a3e42-thumbnail-001",
        "cmd": ["pytest", "backend/tests/test_preview_engine.py", "--timeout=300"]
    }
]

for task in tasks:
    task_id = task["id"]
    cmd = task["cmd"]
    print(f"=== Verifying {task_id} ===")
    print(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"SUCCESS: {task_id} passed tests.")
        hub.mark_task_done(task_id, "pass", report={"status": "success", "msg": "Validated via validate_completed_tasks.py"})
    else:
        print(f"FAILED: {task_id} failed tests. Exit code: {res.returncode}")
        print("Stdout:", res.stdout[:500])
        print("Stderr:", res.stderr[:500])
