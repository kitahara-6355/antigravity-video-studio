import sys
import os
import json
import traceback

# プロジェクトのルートパスを sys.path に追加してインポート可能にする
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(1, backend_path)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import OpusQuotaExceededException


def main() -> int:
    """次のバッチを取得して標準出力に表示するメイン処理。

    Returns:
        int: 終了コード (0: 正常終了, 1: 異常終了)
    """
    try:
        hub = OrchestrationHub()
        state = hub.get_phase_state()
        if not isinstance(state, dict):
            raise TypeError(f"get_phase_state returned non-dict type: {type(state)}")
        if "current_phase" not in state:
            raise KeyError("get_phase_state missing 'current_phase'")
        if "current_milestone" not in state:
            raise KeyError("get_phase_state missing 'current_milestone'")
        
        phase = state["current_phase"]
        milestone = state["current_milestone"]
        
        if not isinstance(phase, int) or isinstance(phase, bool) or phase <= 0:
            raise TypeError(f"current_phase must be a positive int, got {phase}")
        if not isinstance(milestone, str) or not milestone.strip():
            raise TypeError(f"current_milestone must be a non-empty str, got {milestone}")

        batch = hub.get_next_batch(phase, milestone, batch_size=6)
        if batch is None:
            sys.stderr.write("No batch returned.\n")
            return 1
            
        print("BATCH_START")
        print(json.dumps(batch, indent=2, ensure_ascii=False))
        print("BATCH_END")
        return 0
    except (ValueError, KeyError, OSError, json.JSONDecodeError, ImportError, RuntimeError, OpusQuotaExceededException) as e:
        sys.stderr.write(f"Error executing dispatch_next_batch: {type(e).__name__}: {e}\n")
        traceback.print_exc(file=sys.stderr)
        return 1
    except Exception as e:
        try:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            
            # トレースバックから例外が発生した行番号を動的に取得する
            tb = e.__traceback__
            line_number = 0
            if tb:
                current_file_path = os.path.abspath(__file__)
                while tb:
                    frame = tb.tb_frame
                    code = frame.f_code
                    if os.path.abspath(code.co_filename) == current_file_path:
                        line_number = tb.tb_lineno
                        break
                    tb = tb.tb_next
            if line_number == 0:
                import inspect
                frame = inspect.currentframe().f_back
                line_number = frame.f_lineno if frame else 0
                
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/scratch/dispatch_next_batch.py",
                line_number=line_number,
                pattern="dispatch_next_batch.main",
                cause_pattern="DP-01",
                fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
                registered_by="bug_hunter",
                notes=f"Unexpected exception during dispatch execution: {e}",
                tags=["dispatch_next_batch", "except_exception"]
            )
        except Exception as register_err:
            sys.stderr.write(f"Failed to register technical debt: {register_err}\n")
        sys.stderr.write(f"Unexpected error executing dispatch_next_batch: {type(e).__name__}: {e}\n")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

