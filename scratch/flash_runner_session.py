# -*- coding: utf-8 -*-
import sys
import os
import json

# backend and root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    
    # 自身の conversation_id を登録
    conv_id = "ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1"
    hub.register_flash_conversation_id(conv_id)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス出力
    status = hub.generate_flash_status()
    print("=== STATUS_START ===")
    print(status.get("formatted", ""))
    print("=== STATUS_END ===")
    
    # アダプティブアーカイブ判定
    print(f"Archive Urgency: {status.get('archive_urgency', 'none')}")
    print(f"Context Consumption: {status.get('context_consumption_pct', 0)}%")
    
    # 次のバッチ取得
    state = hub.get_phase_state()
    phase = state.get("current_phase", 33)
    milestone = state.get("current_milestone", "M33.1")
    
    # バッチ状態を取得
    queue_status = hub.get_queue_status()
    print(f"Queue Status: {json.dumps(queue_status)}")
    
    batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=6)
    print("=== BATCH_START ===")
    print(json.dumps(batch, ensure_ascii=False, indent=2))
    print("=== BATCH_END ===")

if __name__ == "__main__":
    main()
