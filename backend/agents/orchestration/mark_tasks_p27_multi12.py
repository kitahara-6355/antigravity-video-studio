import sys
import json
import os
import argparse
import traceback
from pathlib import Path

# プロジェクトルートと backend ディレクトリを sys.path に絶対パスで追加
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / 'backend') not in sys.path:
    sys.path.insert(0, str(project_root / 'backend'))

from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import OpusQuotaExceededException

# 定数定義
CONVERSATION_ID = "0f2f32d3-7361-4ed8-b98a-ec10eb70314e"
TARGET_TASK_ID = "T-batch_3f4c3a-thumbnail-000"
DEFAULT_STATUS = "pass"
DEFAULT_DETAILS = {
    "subagent_id": "c5ce3e81-796e-4f96-8454-2caa88a86c62",
    "message": "comprehensive_preview.py サムネイル品質向上 & クロップ中央切抜き追加 & 自動検証テスト追加",
    "changed_files": [
        "backend/comprehensive_preview.py",
        "backend/tests/test_comprehensive_preview.py"
    ]
}

def setup_orchestration_hub(conversation_id: str) -> OrchestrationHub:
    """OrchestrationHub の初期化および会話IDの登録を行う。"""
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(conversation_id)
    return hub

def parse_arguments(args=None):
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="Mark tasks done for multi12.")
    parser.add_argument("--conversation-id", default=CONVERSATION_ID, help="Conversation ID for OrchestrationHub")
    parser.add_argument("--task-id", default=TARGET_TASK_ID, help="Task ID to mark done")
    parser.add_argument("--status", default=DEFAULT_STATUS, choices=["pass", "fail"], help="Task status")
    parser.add_argument("--details", default=None, help="JSON string representing task details")
    parser.add_argument("--debug", action="store_true", help="Print detailed exception traceback")
    return parser.parse_args(args)

def execute_updates(hub: OrchestrationHub, task_id: str, status: str, details: dict) -> None:
    """心拍の更新、およびタスクの完了マークを行う。"""
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク完了のマーク
    hub.mark_task_done(task_id, status, details)
    print(f"Marked {task_id} as {status}.")

def display_flash_status(hub: OrchestrationHub) -> None:
    """現在のステータスを標準出力に表示する。"""
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status.get("formatted", ""))
    print("==============")

def _handle_exception(hub: OrchestrationHub, exception_name: str, e: Exception, message: str, debug: bool = False) -> None:
    """例外発生時のエラーログ送信とクリーンな終了処理。"""
    if hub is not None:
        try:
            hub.flash_report_error(f"{exception_name}: {str(e)}", module="mark_tasks_p27_multi12")
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
        
        hub = setup_orchestration_hub(parsed_args.conversation_id)
        
        if parsed_args.details:
            try:
                details = json.loads(parsed_args.details)
                if not isinstance(details, dict):
                    raise ValueError(f"--details must be a JSON object, got {type(details).__name__}")
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(f"Invalid JSON in --details: {e.msg}", e.doc, e.pos)
        else:
            details = DEFAULT_DETAILS
            
        execute_updates(
            hub,
            parsed_args.task_id,
            parsed_args.status,
            details
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
        _handle_exception(hub, "UnexpectedError", e, f"Unexpected error occurred during task processing: {str(e)}", debug)

if __name__ == "__main__":
    main()
