import os
import sys
import argparse

# プロジェクトルートおよび backend ディレクトリを PYTHONPATH に追加
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub

def update_flash_status(hub: OrchestrationHub, conversation_id: str) -> str:
    """現在のセッションの心拍を更新し、ステータス表示用テキストを生成します。"""
    hub.register_flash_conversation_id(conversation_id)
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    # 2. ステータス取得
    status = hub.generate_flash_status()
    return status["formatted"]

def main():
    parser = argparse.ArgumentParser(description="Update flash status.")
    parser.add_argument("--conversation-id", "-id", type=str, default="29e3010a-cc5e-42a1-ac60-65a68f373df1", help="Conversation ID")
    args = parser.parse_args()
    
    hub = OrchestrationHub()
    formatted_status = update_flash_status(hub, args.conversation_id)
    print(formatted_status)

if __name__ == "__main__":
    main()
