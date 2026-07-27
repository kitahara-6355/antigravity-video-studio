import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # Register current conversation ID
    hub.register_flash_conversation_id("ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1")
    
    # Get next batch for Phase 33 Milestone M33.1 with batch_size=6
    batch = hub.get_next_batch(phase=33, milestone="M33.1", batch_size=6)
    print("New Batch Length:", len(batch))
    
    # Get and print status
    status = hub.generate_flash_status()
    print("STATUS_START")
    print(status["formatted"])
    print("STATUS_END")
    
    # Print raw json
    print("RAW_JSON_START")
    print(json.dumps(status))
    print("RAW_JSON_END")

if __name__ == '__main__':
    main()
