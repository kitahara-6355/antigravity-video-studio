import uuid
import math
import traceback
from typing import Dict, Any, Tuple, Optional

from agents.analyst import Analyst

# Threshold values
MINIMUM_BIAS_THRESHOLD = 1.0

def _get_bias_weight(analyst: Analyst) -> float:
    """Extract bias weight from the analyst's soul data."""
    return analyst.soul['bias_weight']

def _get_or_create_analyst(analyst: Optional[Analyst]) -> Analyst:
    """Retrieve the provided analyst or instantiate a new one."""
    return analyst if analyst is not None else Analyst()

def run_debate(analyst: Analyst) -> Dict[str, Any]:
    """1. 討論シミュレーションを実行する"""
    print("\n🗣️ Phase 1: The Debate")
    res = analyst.process({}, {})
    current_bias = _get_bias_weight(analyst)
    print(f"   Analyst Stance: {res['stance']} (Current Bias: {current_bias:.3f})")
    return res

def trigger_learning(analyst: Analyst, session_id: str, stance: str, outcome: str) -> Tuple[float, float]:
    """3. 学習処理を実行する"""
    print("\n🧠 Phase 3: Learning...")
    old_weight = _get_bias_weight(analyst)
    analyst.learn(session_id, stance, outcome)
    new_weight = _get_bias_weight(analyst)
    print(f"   Analyst Bias: {old_weight:.3f} -> {new_weight:.3f}")
    return old_weight, new_weight

def verify_persistence(new_weight: float) -> Tuple[bool, float]:
    """4. 永続化チェックを実行する"""
    print("\n💾 Phase 4: Persistence Check")
    # Reload from disk
    analyst_reborn = Analyst()
    saved_weight = _get_bias_weight(analyst_reborn)
    
    success = (math.isclose(saved_weight, new_weight) and saved_weight > MINIMUM_BIAS_THRESHOLD)
    if success:
        print(f"✅ SUCCESS: Soul File persisted correctly. Value: {saved_weight:.3f}")
    else:
        print(f"❌ FAILURE: Persistence mismatch. {saved_weight} != {new_weight}")
    return success, saved_weight

def _run_evolution_phases(analyst: Analyst, session_id: str, outcome: str) -> bool:
    """進化シミュレーションの各フェーズを実行する内部ヘルパー関数"""
    # 2. Debate
    res = run_debate(analyst)
    
    # 3. Chairman Action
    print(f"\n⚖️ Phase 2: The Chairman Decision -> {outcome}")
    
    # 4. Learning
    _, new_weight = trigger_learning(analyst, session_id, res['stance'], outcome)
    
    # 5. Persistence Check
    success, _ = verify_persistence(new_weight)
    
    return success

def verify_evolution(analyst: Optional[Analyst] = None, outcome: str = "APPROVE") -> bool:
    """進化プロトコルのシミュレーションおよび検証を行うメイン関数"""
    print("--- 🧬 EVOLUTION PROTOCOL: VERIFICATION START ---")
    
    try:
        # 0. Setup
        session_id = str(uuid.uuid4())
        print(f"🆔 Session ID: {session_id}")
        
        # 1. Instantiate analyst if not provided
        analyst = _get_or_create_analyst(analyst)
            
        # Run phases
        return _run_evolution_phases(analyst, session_id, outcome)
        
    except KeyError as e:
        print(f"❌ FAILURE: Data structure error (Missing key: {e}) occurred during verification.")
        traceback.print_exc()
        return False
    except ValueError as e:
        print(f"❌ FAILURE: Value validation error: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ FAILURE: Unexpected exception occurred during verification: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import os
    import sys
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, backend_dir)
    verify_evolution()
