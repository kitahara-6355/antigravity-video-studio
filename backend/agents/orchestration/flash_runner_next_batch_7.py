import sys
import os
import json

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. 次のバッチを取得 (batch_size=6)
    batch = hub.get_next_batch(phase=27, milestone="M27.1", batch_size=6)
    
    # 結果を出力
    print("=== BATCH_TASKS ===")
    print(json.dumps(batch, indent=2, ensure_ascii=False))
    print("===================")
    
    # 3. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
