import os
import sys
import json
import argparse
from typing import Dict, Any, Optional

# プロジェクトのルートパスを sys.path に追加してインポート可能にする
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# OrchestrationHub と TechnicalDebtStore をインポート
from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def register_technical_debt(line_number: int, pattern: str, notes: str):
    """例外に対する汎用catchが発生した際に技術負債を登録する"""
    try:
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/scratch/dispatch_tasks.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes=notes,
            tags=["dispatch_tasks", "except_exception"]
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as register_err:
        print(f"Failed to register technical debt: {register_err}", file=sys.stderr)

def _parse_arguments(args) -> argparse.Namespace:
    """コマンドライン引数を解析する"""
    parser = argparse.ArgumentParser(description="Dispatch next batch of tasks")
    parser.add_argument("--phase", type=int, help="Target phase number")
    parser.add_argument("--milestone", type=str, help="Target milestone string")
    parser.add_argument("--batch-size", type=int, default=6, help="Batch size (default: 6)")
    return parser.parse_args(args)

def _resolve_phase_and_milestone(
    hub: OrchestrationHub, phase: Optional[int], milestone: Optional[str]
) -> tuple[int, str]:
    """phase または milestone が指定されていない場合に OrchestrationHub から取得して解決する"""
    if phase is not None and milestone is not None:
        return phase, milestone

    try:
        phase_state = hub.get_phase_state()
        if not isinstance(phase_state, dict):
            raise TypeError(f"get_phase_state returned non-dict type: {type(phase_state)}")
        
        resolved_phase = phase
        if resolved_phase is None:
            if "current_phase" not in phase_state:
                raise KeyError("get_phase_state missing 'current_phase'")
            resolved_phase = phase_state["current_phase"]
            if not isinstance(resolved_phase, int):
                raise TypeError(f"current_phase must be int, got {type(resolved_phase)}")
                
        resolved_milestone = milestone
        if resolved_milestone is None:
            if "current_milestone" not in phase_state:
                raise KeyError("get_phase_state missing 'current_milestone'")
            resolved_milestone = phase_state["current_milestone"]
            if not isinstance(resolved_milestone, str):
                raise TypeError(f"current_milestone must be str, got {type(resolved_milestone)}")
                
        return resolved_phase, resolved_milestone
    except (TypeError, KeyError, ValueError, RuntimeError, OSError) as e:
        register_technical_debt(
            line_number=72,
            pattern="except (TypeError, KeyError, ValueError, RuntimeError, OSError) as e:",
            notes=f"Failed to retrieve or parse phase state: {e}"
        )
        print(f"Error retrieving phase state: {e}", file=sys.stderr)
        raise

def _validate_batch_size(batch_size: int) -> None:
    """バッチサイズが正の整数であることを検証する"""
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError(f"batch_size must be a positive integer, got {batch_size}")

def _fetch_next_batch(
    hub: OrchestrationHub, phase: int, milestone: str, batch_size: int
) -> Optional[Dict[str, Any]]:
    """OrchestrationHub から次のタスクバッチを取得する"""
    try:
        batch = hub.get_next_batch(phase, milestone, batch_size=batch_size)
        if batch is None:
            print("Warning: hub.get_next_batch returned None", file=sys.stderr)
            return None
        return batch
    except (OSError, RuntimeError, ValueError, TypeError) as e:
        register_technical_debt(
            line_number=96,
            pattern="except (OSError, RuntimeError, ValueError, TypeError) as e:",
            notes=f"Failed to get next batch: {e}"
        )
        print(f"Error getting next batch: {e}", file=sys.stderr)
        raise

def run_dispatch(args=None) -> Optional[Dict[str, Any]]:
    """タスクをディスパッチし、取得したバッチを返す。"""
    parsed_args = _parse_arguments(args)
    hub = OrchestrationHub()
    
    phase, milestone = _resolve_phase_and_milestone(hub, parsed_args.phase, parsed_args.milestone)
    _validate_batch_size(parsed_args.batch_size)
    
    return _fetch_next_batch(hub, phase, milestone, parsed_args.batch_size)

def main():
    try:
        batch = run_dispatch()
        if batch is not None:
            try:
                print(json.dumps(batch, indent=2, ensure_ascii=False))
            except (TypeError, ValueError) as json_err:
                print(f"JSON serialization error: {json_err}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)
        else:
            print("No batch returned.", file=sys.stderr)
            sys.exit(1)
    except (TypeError, KeyError, ValueError, RuntimeError, OSError) as e:
        print(f"Dispatch failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
