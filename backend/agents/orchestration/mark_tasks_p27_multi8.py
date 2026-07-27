import sys
import os
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def setup_project_path() -> None:
    """スクリプトの配置ディレクトリからプロジェクトルートを算出し、sys.pathに追加する"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

# パス設定の実行
setup_project_path()

# プロジェクトルートが追加された後にインポート
from backend.agents.orchestration import OrchestrationHub

# 定数定義
CONVERSATION_ID = "3ed8fce0-a204-47fd-a220-c27fecf03706"
BATCH_ID = "batch_c4f4d2"
WEAVER_000_TASK_ID = f"T-{BATCH_ID}-test_weaver-000"
WEAVER_001_TASK_ID = f"T-{BATCH_ID}-test_weaver-001"
ERROR_MESSAGE_429 = "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."

def _mark_task_failed(hub: OrchestrationHub, task_id: str, error_message: str) -> None:
    """タスクを失敗としてマークする補助関数"""
    hub.mark_task_done(task_id, "fail", {
        "error": error_message
    })
    logger.info(f"Marked task {task_id} as failed.")

def _mark_task_passed(hub: OrchestrationHub, task_id: str, message: str, changed_files: list[str]) -> None:
    """タスクを成功としてマークする補助関数"""
    hub.mark_task_done(task_id, "pass", {
        "message": message,
        "changed_files": changed_files
    })
    logger.info(f"Marked task {task_id} as passed.")

def mark_weaver_tasks_as_resolved(hub: OrchestrationHub) -> None:
    """test_weaverタスクの実行結果をマークする"""
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    logger.info("Heartbeat updated successfully.")
    
    # 2. test_weaver-000 の失敗マーク
    _mark_task_failed(hub, WEAVER_000_TASK_ID, ERROR_MESSAGE_429)
    
    # 3. test_weaver-001 の成功マーク
    _mark_task_passed(
        hub,
        WEAVER_001_TASK_ID,
        "verify_collaborative_model.py の未カバー行テスト追加完了 (カバレッジ 81% -> 100%)",
        ["backend/tests/test_verify_collaborative_model.py"]
    )
    print("TASKS_MARKED")

def display_hub_status(hub: OrchestrationHub) -> None:
    """OrchestrationHubから現在のステータスを生成し、標準出力に表示する"""
    try:
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except Exception as e:
        logger.error(f"Failed to display flash status: {e}")
        raise

def main() -> None:
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(CONVERSATION_ID)
    
    mark_weaver_tasks_as_resolved(hub)
    display_hub_status(hub)

if __name__ == "__main__":
    main()

