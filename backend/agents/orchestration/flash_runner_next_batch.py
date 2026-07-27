import sys
import json
import logging
from typing import Dict, Any

# プロジェクトルートからのインポートを可能にするためパスを追加
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

logger = logging.getLogger(__name__)

# 定数の命名改善
DEFAULT_CONVERSATION_ID = "bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87"


def initialize_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、会話IDを登録する。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub


def execute_heartbeat(hub: OrchestrationHub) -> None:
    """心拍を更新する (心拍レジリエンス規約に準拠)"""
    hub.flash_update_heartbeat()


def fetch_and_display_batch(
    hub: OrchestrationHub,
    phase: int = 27,
    milestone: str = "M27.1",
    batch_size: int = 6
) -> Dict[str, Any]:
    """次のバッチタスクを取得して標準出力に表示する。"""
    batch = hub.get_next_batch(phase=phase, milestone=milestone, batch_size=batch_size)
    print("=== BATCH_TASKS ===")
    print(json.dumps(batch, indent=2, ensure_ascii=False))
    print("===================")
    return batch


def display_status(hub: OrchestrationHub) -> None:
    """現在のステータスを標準出力に表示する。"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")


def main() -> None:
    """メイン実行フロー"""
    try:
        hub = initialize_hub(DEFAULT_CONVERSATION_ID)
        execute_heartbeat(hub)
        fetch_and_display_batch(hub)
        display_status(hub)
    except Exception as err:
        # TD-923の解消: 例外情報を詳細に記録
        logger.exception("Error in flash_runner_next_batch execution: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()


