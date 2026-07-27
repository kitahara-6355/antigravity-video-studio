# -*- coding: utf-8 -*-
import sys
import json
from typing import List, Dict, Any
import traceback

sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub

TARGET_TASK_ID = "T-batch_a97ee3-test_weaver-001"
FLASH_CONVERSATION_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"

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
    hub = None
    try:
        hub = setup_orchestration_hub(FLASH_CONVERSATION_ID)
        hub.flash_update_heartbeat()
        
        changed_files = [
            "backend/tests/test_decision_logger_branches.py"
        ]
        message = "decision_logger.py のテスト拡充。分岐カバレッジ 99% -> 100% へ向上。"
        
        report = build_completion_report(changed_files, message)
        submit_task_completion(hub, TARGET_TASK_ID, report)
        
        status_str = format_flash_status(hub)
        display_status(status_str)
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"Critical error: Configuration or task queue file not found: {e}", file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"FileNotFoundError: {e}")
            except Exception:
                pass
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Critical error: Failed to parse configuration or state JSON: {e}", file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"JSONDecodeError: {e}")
            except Exception:
                pass
        sys.exit(1)
    except Exception as e:
        print(f"Error during marking tasks: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"Unexpected error: {e}")
            except Exception:
                pass
        sys.exit(1)

if __name__ == "__main__":
    main()

