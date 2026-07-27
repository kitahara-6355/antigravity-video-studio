import sys
import os
import logging

sys.path.insert(0, '.')
# Ensure backend directory is in sys.path to allow importing top-level 'agents' package
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
from backend.agents.orchestration import OrchestrationHub

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 定義値
CONVERSATION_ID = "3ed8fce0-a204-47fd-a220-c27fecf03706"
BATCH_ID = "batch_c4f4d2"
ERROR_MESSAGE = "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."


def mark_thumbnail_tasks_as_failed(hub: OrchestrationHub) -> None:
    """特定のサムネイルタスクを失敗としてマークする。"""
    tasks = [
        "T-batch_c4f4d2-thumbnail-000",
        "T-batch_c4f4d2-thumbnail-001"
    ]
    failed_tasks = []
    for task_id in tasks:
        try:
            hub.mark_task_done(task_id, "fail", {
                "error": ERROR_MESSAGE
            })
            logger.info(f"Successfully marked task {task_id} as failed.")
        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as failed: {e}")
            failed_tasks.append((task_id, e))
            
    if failed_tasks:
        logger.error(f"Some tasks failed to be marked: {[t[0] for t in failed_tasks]}")
        raise failed_tasks[0][1]


def report_batch_failure(hub: OrchestrationHub) -> None:
    """バッチ完了時の失敗レポートを提出する。"""
    try:
        hub.submit_batch_report(BATCH_ID, {
            "passed": 0,
            "failed": 2,
            "skipped": 0,
            "total": 2,
        })
        print("BATCH_SUBMITTED")
        logger.info(f"Successfully submitted batch failure report for {BATCH_ID}.")
    except Exception as e:
        logger.error(f"Failed to submit batch report for {BATCH_ID}: {e}")
        raise


def display_latest_status(hub: OrchestrationHub) -> None:
    """最新のフラッシュステータスを表示する。"""
    try:
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except Exception as e:
        logger.warning(f"Failed to generate or display flash status: {e}")


def main() -> None:
    """OrchestrationHubを使用して、心拍更新、失敗タスクマーク、バッチ報告を行う。"""
    logger.info("Starting task marking script.")
    try:
        hub = OrchestrationHub()
    except Exception as e:
        logger.error(f"Failed to initialize OrchestrationHub: {e}")
        raise

    try:
        hub.register_flash_conversation_id(CONVERSATION_ID)
    except Exception as e:
        logger.error(f"Failed to register flash conversation ID: {e}")
        raise
    
    # 1. 心拍更新
    try:
        hub.flash_update_heartbeat()
        logger.info("Heartbeat updated successfully.")
    except Exception as e:
        logger.error(f"Failed to update flash heartbeat: {e}")
        raise
    
    # 2. thumbnail-000, 001 の失敗マーク
    try:
        mark_thumbnail_tasks_as_failed(hub)
    except Exception as e:
        logger.error(f"Error during thumbnail task marking: {e}")
        raise
    
    # 3. バッチ完了報告
    try:
        report_batch_failure(hub)
    except Exception as e:
        logger.error(f"Error during batch failure reporting: {e}")
        raise
    
    # 4. 最新ステータス表示
    display_latest_status(hub)


if __name__ == "__main__":
    main()
