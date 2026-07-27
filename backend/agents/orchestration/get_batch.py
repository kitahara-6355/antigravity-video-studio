import os
import sys
import json

# プロジェクトのルートパスを sys.path に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.agents.orchestration import OrchestrationHub

def main():
    try:
        hub = OrchestrationHub()
        batch = hub.get_next_batch(phase=27, milestone="M27.1", batch_size=6)
        print("===BATCH===")
        print(json.dumps(batch, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    try:
        os.remove(__file__)
    except OSError:
        pass

if __name__ == "__main__":
    main()
