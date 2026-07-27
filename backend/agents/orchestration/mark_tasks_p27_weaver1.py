# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')
import json
import traceback
from backend.agents.orchestration import OrchestrationHub

# 定数の定義
CONVERSATION_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"
TASK_ID = "T-batch_214e16-test_weaver-001"
REPORT_MESSAGE = "scratch/mark_task_f076d6_005_done.py のテスト拡充。カバレッジ 100% を維持。"
CHANGED_FILES = ["backend/tests/test_scratch_mark_task_f076d6_005_done.py"]


def setup_orchestration_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHubを生成し、会話IDを登録する"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub


def build_completion_report(changed_files: list, message: str) -> dict:
    """タスク完了レポートを構築する"""
    return {
        "message": message,
        "changed_files": changed_files
    }


def submit_task_completion(hub: OrchestrationHub, task_id: str, report: dict) -> None:
    """タスクを完了としてマークし、完了通知を表示する"""
    hub.mark_task_done(task_id, "pass", report)
    display_status("TASK_MARKED_DONE")


def format_flash_status(hub: OrchestrationHub) -> str:
    """最新ステータスを取得し、文字列にフォーマットする"""
    status = hub.generate_flash_status()
    return "FLASH_STATUS:" + json.dumps(status)


def display_status(message: str) -> None:
    """ステータスメッセージを出力する"""
    print(message)


def main() -> None:
    """メイン実行処理と例外ハンドリング"""
    hub = None
    try:
        # 1. Hubのセットアップ
        hub = setup_orchestration_hub(CONVERSATION_ID)

        # 2. 心拍の更新
        hub.flash_update_heartbeat()

        # 3. レポートの構築とタスク完了送信
        report = build_completion_report(CHANGED_FILES, REPORT_MESSAGE)
        submit_task_completion(hub, TASK_ID, report)

        # 4. ステータスの出力
        status_str = format_flash_status(hub)
        display_status(status_str)

        sys.exit(0)

    except FileNotFoundError as e:
        sys.stderr.write(f"Critical error: Configuration or task queue file not found: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"FileNotFoundError: {str(e)}")
            except (OSError, TypeError, ValueError) as hub_err:
                sys.stderr.write(f"Failed to report error to hub: {str(hub_err)}\n")
                traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    except json.JSONDecodeError as e:
        sys.stderr.write(f"Critical error: Failed to parse configuration or state JSON: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"JSONDecodeError: {str(e)}")
            except (OSError, TypeError, ValueError) as hub_err:
                sys.stderr.write(f"Failed to report error to hub: {str(hub_err)}\n")
                traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    except (OSError, TypeError, ValueError, KeyError, AttributeError, RuntimeError) as e:
        sys.stderr.write(f"Error during marking tasks: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)
        if hub is not None:
            try:
                hub.flash_report_error(f"Unexpected error: {str(e)}")
            except (OSError, TypeError, ValueError) as hub_err:
                sys.stderr.write(f"Failed to report error to hub: {str(hub_err)}\n")
                traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
