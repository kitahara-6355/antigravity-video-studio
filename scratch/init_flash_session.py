import sys
import os

# プロジェクトのルートとbackendをパスに追加
sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 自身の conversation_id を登録
    conv_id = "851baf17-cfa5-4c9f-b4d2-9647773dc645"
    hub.register_flash_conversation_id(conv_id)
    print(f"Registered Flash conversation_id: {conv_id}")
    
    # フェーズ情報の取得
    state = hub.get_phase_state()
    print("Phase state:", state)
    
    # バッチ状態の取得
    q_status = hub.get_queue_status()
    print("Queue status:", q_status)

if __name__ == '__main__':
    main()
