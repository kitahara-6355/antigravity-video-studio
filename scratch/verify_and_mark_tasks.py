import sys
sys.path.append('.')
import subprocess
import json
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
# 心拍更新
hub.flash_update_heartbeat()

tasks_to_verify = [
    {
        "id": "T-batch_0152c4-thumbnail-000",
        "test_cmd": ["pytest", "backend/tests/test_preview_engine.py", "--timeout=300"]
    },
    {
        "id": "T-batch_0152c4-thumbnail-003",
        "test_cmd": ["pytest", "backend/tests/test_shared/test_thumbnail_plugin_extra.py", "--timeout=300"]
    },
    {
        "id": "T-batch_0152c4-test_weaver-002",
        "test_cmd": ["pytest", "backend/tests/_test_3tier_fallback.py", "--timeout=300"]
    },
    {
        "id": "T-batch_0152c4-refactor-000",
        "test_cmd": ["pytest", "backend/tests/test_routers_health.py", "--timeout=300"]
    }
]

for item in tasks_to_verify:
    print(f"=== Verifying {item['id']} ===")
    print(f"Running command: {' '.join(item['test_cmd'])}")
    res = subprocess.run(item['test_cmd'], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"SUCCESS: {item['id']} passed tests.")
        hub.mark_task_done(item['id'], "pass", report={"status": "success", "msg": "Validated via validate_completed_tasks.py"})
    else:
        print(f"FAILED: {item['id']} failed. Exit code: {res.returncode}")
        print("--- STDOUT ---")
        print(res.stdout)
        print("--- STDERR ---")
        print(res.stderr)

print("Verification completed.")
