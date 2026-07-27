import sys
import json
import logging
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

logger = logging.getLogger(__name__)

def initialize_hub_with_conversation(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、会話IDの登録および心拍の更新を行います。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub

def fetch_and_display_next_batch(hub: OrchestrationHub, phase: int, milestone: str, batch_size: int) -> list:
    """次のタスクバッチを取得し、フォーマットして表示します。"""
    batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=batch_size)
    print("=== BATCH_TASKS ===")
    print(json.dumps(batch, indent=2, ensure_ascii=False))
    print("===================")
    return batch

def display_current_status(hub: OrchestrationHub) -> dict:
    """現在のシステムステータスを表示し、取得したステータスを返します。"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")
    return status

def main():
    my_conv_id = "3ed8fce0-a204-47fd-a220-c27fecf03706"
    try:
        # 1. OrchestrationHub初期化と心拍更新
        hub = initialize_hub_with_conversation(my_conv_id)
        
        # 2. 次のバッチを取得
        fetch_and_display_next_batch(hub, phase=27, milestone="M27.1", batch_size=8)
        
        # 3. 最新ステータス表示
        display_current_status(hub)
    except BaseException as e:
        logger.error(f"Error in flash_runner_next_batch_6: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
