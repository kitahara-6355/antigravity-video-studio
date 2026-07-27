import sys
import os
import json

# プロジェクトルートを sys.path に追加
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

def main():
    if len(sys.argv) < 5:
        print("Usage: python fetch_batch.py <phase> <milestone> <batch_size> <conversation_id>")
        sys.exit(1)

    phase = int(sys.argv[1])
    milestone = sys.argv[2]
    batch_size = int(sys.argv[3])
    conversation_id = sys.argv[4]

    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()

    # 次のバッチを取得
    batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=batch_size)
    
    print("=== BATCH_TASKS ===")
    print(json.dumps(batch, indent=2, ensure_ascii=False))
    print("===================")

    # ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
