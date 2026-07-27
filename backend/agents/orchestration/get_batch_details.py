"""get_batch_details モジュール。

OrchestrationHub を用いて、現在のフェーズ情報から次のバッチの詳細を取得し、
標準出力に出力するスクリプト。
"""

import os
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
backend_dir = os.path.join(project_root, 'backend')
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.hub_common import OpusQuotaExceededException
import json

def main():
    """現在のフェーズとマイルストーン情報から、次のバッチ詳細を取得して表示する。"""
    try:
        hub = OrchestrationHub()
        # 状態確認
        state = hub.get_phase_state()
        if not state:
            print("Error: Phase state is None or empty.", file=sys.stderr)
            sys.exit(1)
            
        if not isinstance(state, dict):
            raise TypeError(f"Phase state must be a dictionary, got {type(state).__name__}")
            
        phase = state.get("current_phase")
        milestone = state.get("current_milestone")
        if phase is None or milestone is None:
            print(f"Error: Required keys 'current_phase' or 'current_milestone' missing in phase state. state={state}", file=sys.stderr)
            sys.exit(1)
            
        if not isinstance(phase, int):
            raise TypeError(f"current_phase must be an integer, got {type(phase).__name__}")
        if not isinstance(milestone, str):
            raise TypeError(f"current_milestone must be a string, got {type(milestone).__name__}")
        
        print(f"Calling get_next_batch with phase={phase}, milestone={milestone}")
        batch = hub.get_next_batch(phase, milestone, batch_size=6)
        
        if not isinstance(batch, list):
            raise TypeError(f"get_next_batch must return a list, got {type(batch).__name__}")
        print("BATCH_DETAILS:" + json.dumps(batch, indent=2))
    except (FileNotFoundError, PermissionError) as e:
        print(f"Error: File access error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON configuration: {e}", file=sys.stderr)
        sys.exit(1)
    except OpusQuotaExceededException as e:
        print(f"Error: Opus quota exceeded: {e}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, TypeError, KeyError) as e:
        print(f"Error: Invalid configuration or missing keys: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: Runtime error during batch details retrieval: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
