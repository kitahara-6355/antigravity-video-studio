import sys
import os
import json

# 動的なプロジェクトルート解決
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()

    hub.submit_batch_report("batch_769699", {
        "passed": 18,
        "failed": 0,
        "skipped": 12,
        "total": 30
    })

    status = hub.generate_flash_status()
    print("STATUS_START")
    print(json.dumps(status, indent=2, ensure_ascii=False))
    print("STATUS_END")

if __name__ == "__main__":
    main()
