import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    
    # バッチ取得 (NIGHTモードのため batch_size=12)
    batch = hub.get_next_batch(phase=33, milestone="M33.1", batch_size=12)
    print("Batch length:", len(batch))
    for i, t in enumerate(batch):
        print(f"Task {i+1}: ID={t['id']}, Group={t['group']}, Target={t['target_module']}")
        print(f"Prompt template preview: {t.get('prompt_template', '')[:200]}...")

if __name__ == '__main__':
    main()
