import sys
import os
import json

# Add path dynamically if it exists
target_path = "C:/Users/PC_User/Desktop/script/video-automation"
if os.path.exists(target_path) and target_path not in sys.path:
    sys.path.insert(0, target_path)

try:
    from backend.agents.orchestration import OrchestrationHub

    hub = OrchestrationHub()
    hub.flash_update_heartbeat()

    hub.submit_batch_report("batch_c48ea3", {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })

    status = hub.generate_flash_status()
    print("STATUS_START")
    print(json.dumps(status, indent=2, ensure_ascii=False))
    print("STATUS_END")
except Exception as e:
    print(f"Error executing submit_batch_c48ea3: {e}", file=sys.stderr)
    raise
