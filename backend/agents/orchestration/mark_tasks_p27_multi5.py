import sys
import json
import os
import argparse
import traceback

# プロジェクトルートと backend ディレクトリを sys.path に追加して ModuleNotFoundError を防止
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# backend パッケージ自体を解決できるよう backend ディレクトリを sys.path に追加
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import OpusQuotaExceededException

# 定数定義（マジックナンバー・マジックストリングの除去と命名改善）
CONVERSATION_ID = "3ed8fce0-a204-47fd-a220-c27fecf03706"
TARGET_TASK_ID = "T-batch_394f90-tdr_cleanup-000"
BATCH_ID = "batch_394f90"

ERROR_DETAILS = {
    "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."
}

BATCH_SUMMARY = {
    "passed": 2,
    "failed": 6,
    "skipped": 0,
    "total": 8,
}

def setup_orchestration_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHub の初期化および会話IDの登録を行う。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub

def parse_arguments(args=None):
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="Mark tasks and submit batch report to OrchestrationHub.")
    parser.add_argument("--conversation-id", default=CONVERSATION_ID, help="Conversation ID for OrchestrationHub")
    parser.add_argument("--task-id", default=TARGET_TASK_ID, help="Task ID to mark done")
    parser.add_argument("--batch-id", default=BATCH_ID, help="Batch ID to submit report for")
    parser.add_argument("--status", default="fail", choices=["fail", "passed"], help="Task status (fail or passed)")
    parser.add_argument("--error-details", default=None, help="JSON string representing error details")
    parser.add_argument("--batch-summary", default=None, help="JSON string representing batch summary")
    parser.add_argument("--debug", action="store_true", help="Print detailed exception traceback")
    return parser.parse_args(args)

def execute_batch_updates(hub: OrchestrationHub, task_id: str, status: str, error_details: dict, batch_id: str, batch_summary: dict) -> None:
    """心拍の更新、タスクの完了マーク、およびバッチ完了報告を送信する。"""
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク完了マーク
    hub.mark_task_done(task_id, status, error_details)
    
    # 3. バッチ完了報告
    hub.submit_batch_report(batch_id, batch_summary)
    print("BATCH_SUBMITTED")

def display_flash_status(hub: OrchestrationHub) -> None:
    """現在のステータスを標準出力に表示する。"""
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

def _handle_exception(hub: OrchestrationHub, exception_name: str, e: Exception, message: str, debug: bool = False) -> None:
    if hub is not None:
        try:
            hub.flash_report_error(f"{exception_name}: {str(e)}", module="mark_tasks_p27_multi5")
        except Exception as report_err:
            print(f"Failed to report error to hub: {str(report_err)}", file=sys.stderr)
    print(message, file=sys.stderr)
    if debug:
        traceback.print_exc()
    sys.exit(1)

def main(args=None):
    hub = None
    debug = False
    try:
        if args is None:
            is_testing = "pytest" in sys.modules or (len(sys.argv) > 0 and "pytest" in sys.argv[0])
            args = [] if is_testing else sys.argv[1:]
        parsed_args = parse_arguments(args)
        debug = parsed_args.debug
        
        # JSON文字列のパース
        if parsed_args.error_details:
            try:
                error_details = json.loads(parsed_args.error_details)
                if not isinstance(error_details, dict):
                    raise ValueError(f"--error-details must be a JSON object, got {type(error_details).__name__}")
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(f"Invalid JSON in --error-details: {e.msg}", e.doc, e.pos)
        else:
            error_details = ERROR_DETAILS
            
        if parsed_args.batch_summary:
            try:
                batch_summary = json.loads(parsed_args.batch_summary)
                if not isinstance(batch_summary, dict):
                    raise ValueError(f"--batch-summary must be a JSON object, got {type(batch_summary).__name__}")
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(f"Invalid JSON in --batch-summary: {e.msg}", e.doc, e.pos)
        else:
            batch_summary = BATCH_SUMMARY

        hub = setup_orchestration_hub(parsed_args.conversation_id)
        execute_batch_updates(
            hub,
            parsed_args.task_id,
            parsed_args.status,
            error_details,
            parsed_args.batch_id,
            batch_summary
        )
        display_flash_status(hub)
    except json.JSONDecodeError as e:
        _handle_exception(hub, "JSONDecodeError", e, f"JSON decode error occurred: {str(e)}", debug)
    except FileNotFoundError as e:
        _handle_exception(hub, "FileNotFoundError", e, f"Required file not found: {str(e)}", debug)
    except OSError as e:
        _handle_exception(hub, "OSError", e, f"OS error occurred: {str(e)}", debug)
    except ImportError as e:
        _handle_exception(hub, "ImportError", e, f"Import error occurred: {str(e)}", debug)
    except ValueError as e:
        _handle_exception(hub, "ValueError", e, f"Value error occurred: {str(e)}", debug)
    except TypeError as e:
        _handle_exception(hub, "TypeError", e, f"Type error occurred: {str(e)}", debug)
    except KeyError as e:
        _handle_exception(hub, "KeyError", e, f"Key error occurred: {str(e)}", debug)
    except OpusQuotaExceededException as e:
        _handle_exception(hub, "OpusQuotaExceededException", e, f"Opus quota exceeded error: {str(e)}", debug)
    except Exception as e:
        _handle_exception(hub, "UnexpectedError", e, f"Unexpected error occurred during batch task processing: {str(e)}", debug)


if __name__ == "__main__":
    main()

