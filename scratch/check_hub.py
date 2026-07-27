import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
state = hub.get_phase_state()
queue_status = hub.get_queue_status()
print(json.dumps({
    "state": state,
    "queue_status": queue_status
}, indent=2, ensure_ascii=False))
