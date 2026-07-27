import sys
sys.path.insert(0, "C:/Users/PC_User/Desktop/script/video-automation")
import json
import traceback
from backend.agents.orchestration import OrchestrationHub

try:
    hub = OrchestrationHub()
    state = hub.get_phase_state()
    status = hub.generate_flash_status()
    queue_status = hub.get_queue_status()

    print(json.dumps({
        "state": state,
        "status": status,
        "queue_status": queue_status
    }, indent=2, ensure_ascii=False))
except Exception as e:
    sys.stderr.write(json.dumps({
        "error": str(e),
        "traceback": traceback.format_exc()
    }, indent=2, ensure_ascii=False) + "\n")
    sys.exit(1)


