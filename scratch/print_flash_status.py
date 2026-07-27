import sys
import os

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    status = hub.generate_flash_status()
    print("FORMATTED_START")
    print(status["formatted"])
    print("FORMATTED_END")
    print("RAW_JSON_START")
    import json
    print(json.dumps(status))
    print("RAW_JSON_END")

if __name__ == '__main__':
    main()
