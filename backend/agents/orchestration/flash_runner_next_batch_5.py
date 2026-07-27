import sys
import json
import logging
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

logger = logging.getLogger(__name__)

DEFAULT_FLASH_CONVERSATION_ID = "3ed8fce0-a204-47fd-a220-c27fecf03706"

def initialize_orchestration_hub(conversation_id: str = DEFAULT_FLASH_CONVERSATION_ID) -> OrchestrationHub:
    """OrchestrationHubを初期化し、Flashの会話IDを登録します。"""
    orchestration_hub = OrchestrationHub()
    orchestration_hub.register_flash_conversation_id(conversation_id)
    return orchestration_hub

def update_flash_heartbeat(orchestration_hub: OrchestrationHub) -> None:
    """Flashセッションの心拍の更新を行います。"""
    orchestration_hub.flash_update_heartbeat()

def fetch_next_task_batch(
    orchestration_hub: OrchestrationHub, phase: int = 27, milestone: str = "M27.1", batch_size: int = 8
) -> dict:
    """次のバッチタスクを取得します。"""
    return orchestration_hub.get_next_batch(phase=phase, milestone=milestone, batch_size=batch_size)

def format_task_batch(batch: dict) -> str:
    """バッチタスク情報をフォーマットします。"""
    formatted_json = json.dumps(batch, indent=2, ensure_ascii=False)
    return f"=== BATCH_TASKS ===\n{formatted_json}\n==================="

def print_task_batch(batch: dict) -> None:
    """バッチタスク情報を標準出力に表示します。"""
    print(format_task_batch(batch))

def fetch_flash_status(orchestration_hub: OrchestrationHub) -> dict:
    """最新のFlashセッションステータスを取得します。"""
    return orchestration_hub.generate_flash_status()

def format_flash_session_status(status: dict) -> str:
    """Flashセッションステータスをフォーマットします。"""
    status_content = status.get("formatted", "")
    return f"=== STATUS ===\n{status_content}\n=============="

def print_flash_session_status(status: dict) -> None:
    """Flashセッションステータスを標準出力に表示します。"""
    print(format_flash_session_status(status))

def execute_flash_sequence(orchestration_hub: OrchestrationHub) -> tuple[dict, dict]:
    """心拍の更新、バッチ取得、最新ステータス取得を行い、その結果を返します。"""
    update_flash_heartbeat(orchestration_hub)
    batch = fetch_next_task_batch(orchestration_hub)
    status = fetch_flash_status(orchestration_hub)
    return batch, status

def display_flash_sequence_results(batch: dict, status: dict) -> None:
    """バッチタスクとFlashステータスの情報を出力表示します。"""
    print_task_batch(batch)
    print_flash_session_status(status)

def execute_and_display_flash_sequence(orchestration_hub: OrchestrationHub) -> None:
    """Flashの実行シーケンス（心拍更新、バッチ取得、ステータス取得）を一括実行し、結果を出力します。"""
    batch, status = execute_flash_sequence(orchestration_hub)
    display_flash_sequence_results(batch, status)

def _is_configuration_or_known_runtime_error(e: Exception) -> bool:
    """例外が設定エラーまたは一般的な実行時エラーであるかチェックします。"""
    return isinstance(e, (ValueError, KeyError, RuntimeError, json.JSONDecodeError, OSError))

def log_execution_error(e: Exception) -> int:
    """メイン実行時の例外をハンドリングし、適切にログ出力して終了コードを返します。"""
    if _is_configuration_or_known_runtime_error(e):
        logger.error(f"Error in flash_runner_next_batch_5: Configuration or runtime error: {e}")
    else:
        logger.error(f"Error in flash_runner_next_batch_5: Unexpected error: {e}")
    return 1

def main() -> None:
    exit_code = 0
    try:
        orchestration_hub = initialize_orchestration_hub()
        execute_and_display_flash_sequence(orchestration_hub)
    except Exception as e:
        exit_code = log_execution_error(e)
        sys.exit(exit_code)

if __name__ == "__main__":
    main()


