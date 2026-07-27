import sys
import os
import json
from typing import Dict, Any, Tuple

# PYTHONPATHの追加
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, "backend")
if backend_path not in sys.path:
    sys.path.insert(1, backend_path)

from backend.agents.orchestration import OrchestrationHub


def get_orchestration_hub() -> OrchestrationHub:
    """OrchestrationHubインスタンスを作成して返します。"""
    return OrchestrationHub()


def get_current_phase_info(hub: OrchestrationHub) -> Tuple[int, str]:
    """現在のフェーズとマイルストーン情報を取得します。"""
    state = hub.get_phase_state()
    if not state:
        raise ValueError("フェーズ状態の取得に失敗しました。")
    
    current_phase = state["current_phase"]
    current_milestone = state["current_milestone"]
    return current_phase, current_milestone


def fetch_and_show_next_batch(
    hub: OrchestrationHub, phase: int, milestone: str, batch_size: int = 6
) -> Dict[str, Any]:
    """次のバッチを取得し、フォーマットされたJSONを表示します。"""
    batch = hub.get_next_batch(phase, milestone, batch_size=batch_size)
    print(json.dumps(batch, indent=2))
    
    q_status = hub.get_queue_status()
    print("Queue status after get_next_batch:", q_status)
    return batch


def main() -> None:
    """メイン実行フロー"""
    is_backend = __name__.startswith("backend.")
    
    if is_backend:
        try:
            hub = get_orchestration_hub()
            state = hub.get_phase_state()
            
            # バリデーション
            if state is None:
                print("Validation Error: Phase state is None")
                return
            if not isinstance(state, dict):
                print("Validation Error: Phase state is not a dictionary")
                return
            if "current_phase" not in state:
                print("Validation Error: 'current_phase' key is missing in phase state")
                return
            if "current_milestone" not in state:
                print("Validation Error: 'current_milestone' key is missing in phase state")
                return
                
            phase = state["current_phase"]
            milestone = state["current_milestone"]
            
            print(f"Current Phase: {phase}, Milestone: {milestone}")
            print("Next batch:")
            
            batch = hub.get_next_batch(phase, milestone, batch_size=4)
            print(json.dumps(batch, indent=2))
            
            q_status = hub.get_queue_status()
            print("Queue status after get_next_batch:", q_status)
            
        except Exception as e:
            print(f"Error: {e}")
    else:
        hub = get_orchestration_hub()
        phase, milestone = get_current_phase_info(hub)
        fetch_and_show_next_batch(hub, phase, milestone, batch_size=6)


if __name__ == "scratch.get_next_batch" or __name__ == "__main__":
    main()
