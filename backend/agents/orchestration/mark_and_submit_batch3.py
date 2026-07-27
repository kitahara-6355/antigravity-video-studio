import sys
sys.path.insert(0, '.')
import json
from backend.agents.orchestration import OrchestrationHub

# 定数の定義（命名改善）
FLASH_CONVERSATION_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"
THUMBNAIL_TASK_ID = "T-batch_a97ee3-thumbnail-001"
BATCH_ID = "batch_a97ee3"


def initialize_hub_with_conversation(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHub を初期化し、会話 ID を登録して心拍を更新します。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub


def complete_thumbnail_task(hub: OrchestrationHub, task_id: str) -> None:
    """特定のサムネイルタスクを完了（pass）としてマークします。"""
    task_metadata = {
        "message": "agents/workers/proofread_worker.py & routers/preview.py のサムネイル処理改善と品質検証・テスト追加。",
        "changed_files": [
            "backend/agents/workers/proofread_worker.py",
            "backend/routers/preview.py",
            "backend/tests/test_thumbnail_quality_extra.py"
        ]
    }
    hub.mark_task_done(task_id, "pass", task_metadata)


def submit_batch_report(hub: OrchestrationHub, batch_id: str) -> None:
    """バッチ全体の実行結果レポートを送信します。"""
    report_data = {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6,
    }
    hub.submit_batch_report(batch_id, report_data)
    print("BATCH_SUBMITTED")


def print_flash_status(hub: OrchestrationHub) -> None:
    """現在の Flash のステータスを JSON 形式で出力します。"""
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))


def main() -> None:
    # 1. Hubの初期化と会話ID登録・心拍更新
    hub = initialize_hub_with_conversation(FLASH_CONVERSATION_ID)
    
    # 2. タスクの完了処理
    complete_thumbnail_task(hub, THUMBNAIL_TASK_ID)
    
    # 3. バッチレポートの送信
    submit_batch_report(hub, BATCH_ID)
    
    # 4. ステータスの表示
    print_flash_status(hub)


if __name__ == "__main__":
    main()
