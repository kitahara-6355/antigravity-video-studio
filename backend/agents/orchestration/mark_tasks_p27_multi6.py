import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

# デフォルト設定値の定義
DEFAULT_FLASH_CONVERSATION_ID = "3ed8fce0-a204-47fd-a220-c27fecf03706"
DEFAULT_TARGET_TASK_ID = "T-batch_c4f4d2-thumbnail-001"
DEFAULT_FAILURE_DETAILS = {
    "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."
}

def create_and_register_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、会話IDを登録する。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub

def update_hub_heartbeat(hub: OrchestrationHub) -> None:
    """OrchestrationHubの心拍を更新する。"""
    hub.flash_update_heartbeat()

def mark_task_failure(hub: OrchestrationHub, task_id: str, details: dict) -> None:
    """指定されたタスクを失敗としてマークする。"""
    hub.mark_task_done(task_id, "fail", details)

def log_task_failure_completion() -> None:
    """タスク失敗マーク完了のログを出力する。"""
    print("TASK_MARKED_FAIL")

def process_task_failure_pipeline(hub: OrchestrationHub, task_id: str, details: dict) -> None:
    """心拍を更新し、タスクを失敗としてマークして、完了ログを出力する一連の処理を実行する。"""
    update_hub_heartbeat(hub)
    mark_task_failure(hub, task_id, details)
    log_task_failure_completion()

def display_latest_status(hub: OrchestrationHub) -> None:
    """最新のステータス情報を取得し、標準出力に表示する。"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

def main() -> None:
    hub = create_and_register_hub(DEFAULT_FLASH_CONVERSATION_ID)
    process_task_failure_pipeline(hub, DEFAULT_TARGET_TASK_ID, DEFAULT_FAILURE_DETAILS)
    display_latest_status(hub)

if __name__ == "__main__":
    main()
