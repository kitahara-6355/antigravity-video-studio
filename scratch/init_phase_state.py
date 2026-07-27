import json
from pathlib import Path
from datetime import datetime

def main():
    state_path = Path("backend/agents/memory/phase_state.json")
    if not state_path.exists():
        print(f"Error: {state_path} does not exist.")
        return
        
    with open(state_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # phase_started_at を現在時刻(UTC ISO8601)に設定
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data["phase_started_at"] = now_utc
    
    # 状態の初期化
    data["flash_batches_completed"] = 0
    data["flash_tasks_total"] = 0
    data["flash_tasks_passed"] = 0
    data["flash_tasks_failed"] = 0
    data["awaiting_opus"] = False
    data["emergency_stop"] = False
    data["throttled"] = False
    
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully initialized {state_path} with phase_started_at = {now_utc}")

if __name__ == "__main__":
    main()
