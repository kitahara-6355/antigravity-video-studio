import os
import sys
import json
import argparse
from typing import Dict, Any, Optional

# プロジェクトのルートパスと backend パスを sys.path に追加してインポート可能にする
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
backend_dir = os.path.join(project_root, "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# OrchestrationHub と TechnicalDebtStore をインポート
from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def register_technical_debt(line_number: int, pattern: str, notes: str):
    """例外に対する汎用catchが発生した際に技術負債を登録する"""
    try:
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="scratch/dispatch_next_batch_2.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes=notes,
            tags=["dispatch_next_batch_2", "except_exception"]
        )
    except Exception as register_err:
        print(f"Failed to register technical debt: {register_err}", file=sys.stderr)

def run_dispatch(args=None) -> Optional[Dict[str, Any]]:
    """タスクをディスパッチするか、心拍更新を行い、結果を返す。"""
    parser = argparse.ArgumentParser(description="Dispatch next batch of tasks v2")
    parser.add_argument("--phase", type=int, help="Target phase number")
    parser.add_argument("--milestone", type=str, help="Target milestone string")
    parser.add_argument("--batch-size", type=int, default=6, help="Batch size (default: 6)")
    parser.add_argument("--heartbeat-only", action="store_true", help="Only update flash heartbeat and exit")
    parser.add_argument("--update-heartbeat", action="store_true", help="Update heartbeat before dispatching")
    
    parsed_args = parser.parse_args(args)
    
    hub = OrchestrationHub()
    
    # 1. 心拍のみ更新のモード
    if parsed_args.heartbeat_only:
        try:
            hub.flash_update_heartbeat()
            return {"heartbeat_only": True}
        except Exception as e:
            register_technical_debt(
                line_number=53,
                pattern="except Exception as e:",
                notes=f"Failed to update heartbeat: {e}"
            )
            print(f"Error updating heartbeat: {e}", file=sys.stderr)
            raise

    # 2. 事前に心拍更新を行うモード
    if parsed_args.update_heartbeat:
        try:
            hub.flash_update_heartbeat()
        except Exception as e:
            register_technical_debt(
                line_number=66,
                pattern="except Exception as e:",
                notes=f"Failed to update heartbeat (pre-dispatch): {e}"
            )
            print(f"Error updating heartbeat (pre-dispatch): {e}", file=sys.stderr)
            raise

    phase = parsed_args.phase
    milestone = parsed_args.milestone
    batch_size = parsed_args.batch_size
    
    # phase または milestone が指定されていない場合は OrchestrationHub から取得する
    if phase is None or milestone is None:
        try:
            state = hub.get_phase_state()
            if not isinstance(state, dict):
                raise TypeError(f"get_phase_state returned non-dict type: {type(state)}")
            
            if phase is None:
                if "current_phase" not in state:
                    raise KeyError("get_phase_state missing 'current_phase'")
                phase = state["current_phase"]
                if not isinstance(phase, int):
                    raise TypeError(f"current_phase must be int, got {type(phase)}")
                    
            if milestone is None:
                if "current_milestone" not in state:
                    raise KeyError("get_phase_state missing 'current_milestone'")
                milestone = state["current_milestone"]
                if not isinstance(milestone, str):
                    raise TypeError(f"current_milestone must be str, got {type(milestone)}")
        except Exception as e:
            register_technical_debt(
                line_number=99,
                pattern="except Exception as e:",
                notes=f"Failed to retrieve or parse phase state: {e}"
            )
            print(f"Error retrieving phase state: {e}", file=sys.stderr)
            raise
            
    # batch_size のバリデーション
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError(f"batch_size must be a positive integer, got {batch_size}")
        
    try:
        batch = hub.get_next_batch(phase, milestone, batch_size=batch_size)
        if batch is None:
            print("Warning: hub.get_next_batch returned None", file=sys.stderr)
            return None
        return batch
    except Exception as e:
        register_technical_debt(
            line_number=118,
            pattern="except Exception as e:",
            notes=f"Failed to get next batch: {e}"
        )
        print(f"Error getting next batch: {e}", file=sys.stderr)
        raise

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
            except (TypeError, ValueError) as json_err:
                print(f"JSON serialization error: {json_err}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
        else:
            print("No batch returned.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        register_technical_debt(
            line_number=146,
            pattern="except Exception as e:",
            notes=f"Dispatch failed: {e}"
        )
        print(f"Dispatch failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
