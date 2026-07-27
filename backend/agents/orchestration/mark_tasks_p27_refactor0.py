import sys
import json
from typing import List, Dict, Any

sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

TARGET_TASK_ID = 'T-batch_500d23-refactor-000'
FLASH_CONVERSATION_ID = '819c8bbd-e916-476d-b8a1-8582dedb4659'

def setup_orchestration_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを初期化し、FlashのConversation IDを登録します。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub

def build_completion_report(changed_files: List[str], message: str) -> Dict[str, Any]:
    """タスク完了用のレポートデータを構築します。"""
    return {
        'message': message,
        'changed_files': changed_files
    }

def submit_task_completion(
    hub: OrchestrationHub,
    task_id: str,
    report: Dict[str, Any]
) -> None:
    """構築されたレポートを用いてタスクを完了としてマークします。"""
    hub.mark_task_done(task_id, 'pass', report)
    print('TASK_MARKED_DONE')

def format_flash_status(hub: OrchestrationHub) -> str:
    """Flashのステータスを取得し、JSON文字列フォーマットに変換します。"""
    status = hub.generate_flash_status()
    return 'FLASH_STATUS:' + json.dumps(status)

def display_status(status_str: str) -> None:
    """ステータス文字列を出力します。"""
    print(status_str)

def main() -> None:
    hub = setup_orchestration_hub(FLASH_CONVERSATION_ID)
    hub.flash_update_heartbeat()
    
    changed_files = [
        'backend/agents/orchestration/mark_tasks_p27_refactor0.py',
        'backend/tests/test_mark_tasks_p27_refactor0.py'
    ]
    message = 'agents/orchestration/mark_tasks_p27_refactor0.py: dead code removal, name improvement, function splitting.'
    
    report = build_completion_report(changed_files, message)
    submit_task_completion(hub, TARGET_TASK_ID, report)
    
    status_str = format_flash_status(hub)
    display_status(status_str)

if __name__ == '__main__':
    main()
