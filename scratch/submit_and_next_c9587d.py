import sys
sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation")
sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation\backend")

import json
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
try:
    print("SUBMITTING_REPORT...")
    hub.submit_batch_report("batch_c9587d", {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6
    })
    print("SUCCESS_SUBMIT")
    
    print("GETTING_NEXT_BATCH...")
    batch = hub.get_next_batch(33, "M33.1", batch_size=6)
    print("NEXT_BATCH_LEN:", len(batch) if batch else 0)
    print("NEXT_BATCH:")
    print(json.dumps(batch, indent=2, ensure_ascii=False) if batch else "None")
    
    status = hub.generate_flash_status()
    print("STATUS_FORMATTED_START")
    print(status["formatted"])
    print("STATUS_FORMATTED_END")
except Exception as e:
    import traceback
    print("ERROR:", e)
    traceback.print_exc()
