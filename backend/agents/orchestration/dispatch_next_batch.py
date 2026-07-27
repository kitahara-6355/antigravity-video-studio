import os
import sys
import json
import argparse
import inspect
import traceback
from typing import Dict, Any, Optional
import contextlib

# プロジェクトのルートパスを sys.path に追加してインポート可能にする
script_dir = os.path.dirname(os.path.abspath(__file__))
# 親が適用したときのパス（backend/agents/orchestration/）から見て、プロジェクトルートは3階層上
project_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore
from backend.agents.orchestration.hub_common import OpusQuotaExceededException


def register_technical_debt(pattern: str, notes: str, line_number: Optional[int] = None, exception: Optional[Exception] = None):
    """例外に対する汎用catchが発生した際に技術負債を登録する"""
    try:
        if line_number is None:
            if exception is not None and exception.__traceback__ is not None:
                tb = exception.__traceback__
                while tb:
                    frame = tb.tb_frame
                    code = frame.f_code
                    filename = os.path.basename(code.co_filename)
                    if filename == "dispatch_next_batch.py":
                        line_number = tb.tb_lineno
                    tb = tb.tb_next
            
            if line_number is None:
                frame = inspect.currentframe().f_back
                line_number = frame.f_lineno if frame else 0
        
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="agents/orchestration/dispatch_next_batch.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリエーションを適用する",
            registered_by="sprint_thumbnail",
            notes=notes,
            tags=["dispatch_next_batch", "except_exception"]
        )
    except Exception as register_err:
        print(f"Failed to register technical debt: {register_err}", file=sys.stderr)

@contextlib.contextmanager
def handle_hub_exceptions(pattern: str, error_prefix: str):
    """OrchestrationHubの例外ハンドリングを共通化するコンテキストマネージャ"""
    try:
        yield
    except OpusQuotaExceededException as e:
        print(f"OpusQuotaExceededError {error_prefix} (quota limit reached): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    except json.JSONDecodeError as e:
        print(f"JSONDecodeError {error_prefix} (config corruption?): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        print(f"Error ({type(e).__name__}) {error_prefix}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    except OSError as e:
        print(f"OSError ({type(e).__name__}) {error_prefix}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    except Exception as e:
        register_technical_debt(
            pattern=pattern,
            notes=f"Failed to {error_prefix}: {e}",
            exception=e
        )
        print(f"Unexpected error ({type(e).__name__}) {error_prefix}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise

def run_dispatch(args=None) -> Optional[Dict[str, Any]]:
    """次のバッチを取得するか、心拍更新を行い、結果を返す。"""
    parser = argparse.ArgumentParser(description="Dispatch next batch of tasks", exit_on_error=False)
    parser.add_argument("--phase", type=int, help="Target phase number")
    parser.add_argument("--milestone", type=str, help="Target milestone string")
    parser.add_argument("--batch-size", type=int, default=6, help="Batch size (default: 6)")
    parser.add_argument("--heartbeat-only", action="store_true", help="Only update flash heartbeat and exit")
    parser.add_argument("--update-heartbeat", action="store_true", help="Update heartbeat before dispatching")
    parser.add_argument("--conversation-id", type=str, default="ce05d36d-f2c8-452b-8ea9-9053a1e718a0",
                        help="Antigravity conversation ID for heartbeat registration")
    
    try:
        parsed_args = parser.parse_args(args)
    except argparse.ArgumentError as e:
        raise ValueError(f"Invalid command line arguments: {e}") from e
    
    # 早期バリデーション
    if not isinstance(parsed_args.conversation_id, str) or not parsed_args.conversation_id.strip():
        raise ValueError("conversation_id must be a non-empty string")
        
    if parsed_args.phase is not None:
        if not isinstance(parsed_args.phase, int) or parsed_args.phase <= 0:
            raise ValueError(f"phase must be a positive integer, got {parsed_args.phase}")
            
    if parsed_args.milestone is not None:
        if not isinstance(parsed_args.milestone, str) or not parsed_args.milestone.strip():
            raise ValueError("milestone must be a non-empty string")

    if parsed_args.batch_size is not None:
        if not isinstance(parsed_args.batch_size, int) or parsed_args.batch_size <= 0:
            raise ValueError(f"batch_size must be a positive integer, got {parsed_args.batch_size}")
            
    with handle_hub_exceptions("hub.init", "initializing OrchestrationHub"):
        hub = OrchestrationHub()
    
    # 会話IDの登録
    with handle_hub_exceptions("hub.register_flash_conversation_id", "registering conversation ID"):
        hub.register_flash_conversation_id(parsed_args.conversation_id)

    # 1. 心拍のみ更新のモード
    if parsed_args.heartbeat_only:
        with handle_hub_exceptions("hub.flash_update_heartbeat", "updating heartbeat"):
            hub.flash_update_heartbeat()
            return {"heartbeat_only": True}

    # 2. 事前に心拍更新を行うモード
    if parsed_args.update_heartbeat:
        with handle_hub_exceptions("hub.flash_update_heartbeat (pre-dispatch)", "updating heartbeat (pre-dispatch)"):
            hub.flash_update_heartbeat()

    phase = parsed_args.phase
    milestone = parsed_args.milestone
    batch_size = parsed_args.batch_size
    
    # phase または milestone が指定されていない場合は OrchestrationHub から取得する
    if phase is None or milestone is None:
        with handle_hub_exceptions("hub.get_phase_state", "retrieving or parsing phase state"):
            state = hub.get_phase_state()
            if not isinstance(state, dict):
                raise TypeError(f"get_phase_state returned non-dict type: {type(state)}")
            
            if phase is None:
                if "current_phase" not in state:
                    raise KeyError("get_phase_state missing 'current_phase'")
                phase = state["current_phase"]
                if not isinstance(phase, int) or phase <= 0:
                    raise TypeError(f"current_phase must be a positive int, got {phase}")
                    
            if milestone is None:
                if "current_milestone" not in state:
                    raise KeyError("get_phase_state missing 'current_milestone'")
                milestone = state["current_milestone"]
                if not isinstance(milestone, str) or not milestone.strip():
                    raise TypeError(f"current_milestone must be a non-empty str, got {milestone}")
            
    with handle_hub_exceptions("hub.get_next_batch", "getting next batch"):
        batch = hub.get_next_batch(phase, milestone, batch_size=batch_size)
        if batch is None:
            print("Warning: hub.get_next_batch returned None", file=sys.stderr)
            return None
        
        # キューの最新状態とステータス情報を取得して結果を組み立てる
        q_status = hub.get_queue_status()
        status = hub.generate_flash_status()
        
        return {
            "phase": phase,
            "milestone": milestone,
            "batch": batch,
            "queue_status": q_status,
            "status": status
        }

def main():
    try:
        res = run_dispatch()
        if res is not None:
            if "heartbeat_only" in res and res["heartbeat_only"]:
                print("HEARTBEAT_UPDATED")
                sys.exit(0)
            
            try:
                print("BATCH_START")
                print(json.dumps(res, indent=2, ensure_ascii=False))
                print("BATCH_END")
            except (TypeError, ValueError, AttributeError) as json_err:
                print(f"JSON serialization error: {json_err}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
        else:
            print("No batch returned.", file=sys.stderr)
            sys.exit(1)
    except OpusQuotaExceededException as e:
        print(f"Dispatch failed due to Opus quota limit (weekly limit reached): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Dispatch failed due to JSON decode error (config file might be corrupted)", file=sys.stderr)
        print(f"Dispatch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        print(f"Dispatch failed due to parameter or data error ({type(e).__name__})", file=sys.stderr)
        print(f"Dispatch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Dispatch failed due to I/O error ({type(e).__name__})", file=sys.stderr)
        print(f"Dispatch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        register_technical_debt(
            pattern="dispatch_next_batch.main",
            notes=f"Unexpected exception during dispatch execution: {e}",
            exception=e
        )
        print(f"Dispatch failed due to unexpected error ({type(e).__name__}): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
