import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    
    # 次のバッチを取得
    # NIGHTモードのため batch_size=12
    batch = hub.get_next_batch(phase=33, milestone="M33.1", batch_size=12)
    print("New Batch Length:", len(batch))
    
    # 状態取得
    status = hub.generate_flash_status()
    print("STATUS_START")
    print(status["formatted"])
    print("STATUS_END")
    print("STATUS_JSON")
    print(json.dumps(status))

if __name__ == '__main__':
    main()
