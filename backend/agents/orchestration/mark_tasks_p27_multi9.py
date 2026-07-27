import sys
import os
import json
import logging
import subprocess

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

# ロギング設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    """
    OrchestrationHub を使用して、指定されたバッチ内の特定のタスクを
    タイムアウト（スキップ）としてマークし、バッチ完了を報告する。
    
    例外発生時はログを出力した上で、呼び出し元に例外を再送出する。
    """
    logger.info("Starting task marking and batch report submission.")
    
    try:
        hub = OrchestrationHub()
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Failed to initialize OrchestrationHub: {e}")
        raise

    try:
        # 会話IDを登録
        hub.register_flash_conversation_id("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
    except (OSError, TimeoutError) as e:
        logger.error(f"Failed to register flash conversation ID: {e}")
        raise
    
    # 1. 心拍更新
    try:
        hub.flash_update_heartbeat()
        print("Heartbeat updated.")
    except (OSError, TimeoutError) as e:
        logger.error(f"Failed to update flash heartbeat: {e}")
        raise
    
    batch_id = "batch_6ff381"
    tasks = [
        "T-batch_6ff381-thumbnail-000",
        "T-batch_6ff381-thumbnail-001",
        "T-batch_6ff381-test_weaver-000",
        "T-batch_6ff381-test_weaver-001",
        "T-batch_6ff381-bug_hunter-000",
        "T-batch_6ff381-refactor-000"
    ]
    
    # 2. 各タスクをタイムアウト(skip)としてマーク
    # 個別のタスク更新失敗でループが途切れないようにする
    failed_tasks = []
    for task_id in tasks:
        try:
            hub.mark_task_done(task_id, "skip", {
                "error": "SUBAGENT_TIMEOUT: 600秒以内に完了せず自動スキップ",
                "changed_files": []
            })
            print(f"Marked {task_id} as skip.")
        except (OSError, TimeoutError) as e:
            logger.error(f"Failed to mark {task_id} as skip: {e}")
            failed_tasks.append((task_id, e))
            
    # 3. バッチ完了報告
    try:
        hub.submit_batch_report(batch_id, {
            "passed": 0,
            "failed": 0,
            "skipped": 6,
            "total": 6,
        })
        print("Batch report submitted.")
    except (OSError, TimeoutError, subprocess.SubprocessError) as e:
        logger.error(f"Failed to submit batch report: {e}")
        raise
    
    # 4. 最新ステータス表示
    try:
        status = hub.generate_flash_status()
        print("=== STATUS ===")
        print(status["formatted"])
        print("==============")
    except (OSError, TimeoutError) as e:
        logger.warning(f"Failed to generate or display flash status: {e}")

    # 個別タスクで発生した例外を最後に処理して再送出する
    if failed_tasks:
        logger.error(f"Some tasks failed to be marked: {[t[0] for t in failed_tasks]}")
        raise failed_tasks[0][1]

if __name__ == '__main__':
    main()
