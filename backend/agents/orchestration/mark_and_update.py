# -*- coding: utf-8 -*-
import sys
import json
from typing import Dict, Any

# __main__ 実行時のパス追加
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, '.')

from backend.agents.orchestration import OrchestrationHub

def initialize_hub_and_session(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、会話IDを登録して心拍を更新します。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    hub.flash_update_heartbeat()
    return hub

def mark_task_as_done(hub: OrchestrationHub, task_id: str, report: Dict[str, Any]) -> None:
    """指定されたタスクIDを完了としてマークし、レポートを提出します。"""
    hub.mark_task_done(task_id, "pass", report)
    print("TASK_MARKED_DONE")

def display_latest_flash_status(hub: OrchestrationHub) -> None:
    """最新のFlashステータスを取得し、標準出力に表示します。"""
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

def execute_default_update() -> None:
    """デフォルトのタスク更新フローを実行します。"""
    conversation_id = "c34fe890-df08-40c8-bcda-07b5485dbe94"
    task_id = "T-batch_05cb80-bug_hunter-000"
    report = {
        "message": "combined_overlay.py に対し、_has_audio 内で res.stdout が None になる場合の TypeError バグを修正し、安全に空文字にフォールバックするロジックを実装。これを検証するテストおよびffprobeエラー時のフォールバック動作を検証する2つのテストを追加し、正常にPASSすることを確認。",
        "changed_files": [
            "backend/combined_overlay.py",
            "backend/tests/test_combined_overlay.py"
        ]
    }
    
    hub = initialize_hub_and_session(conversation_id)
    mark_task_as_done(hub, task_id, report)
    display_latest_flash_status(hub)

def main():
    execute_default_update()

if __name__ == "__main__":
    main()
