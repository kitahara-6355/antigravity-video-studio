import sys
import json
from backend.agents.orchestration import OrchestrationHub

def main():
    try:
        hub = OrchestrationHub()
        status = hub.generate_flash_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()
