import sys
sys.path.insert(0, "C:/Users/PC_User/Desktop/script/video-automation")
import json
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
hub.flash_update_heartbeat()

hub.submit_batch_report("batch_f076d6", {
    "passed": 6,
    "failed": 0,
    "skipped": 0,
    "total": 6
})

status = hub.generate_flash_status()
print("STATUS_START")
print(json.dumps(status, indent=2, ensure_ascii=False))
print("STATUS_END")
