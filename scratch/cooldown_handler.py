import sys
sys.path.append('.')
sys.path.append('backend')
from backend.agents.orchestration import OrchestrationHub
import json
import time
from pathlib import Path

def main():
    hub = OrchestrationHub()

    # 心拍更新 (最優先)
    hub.flash_update_heartbeat()
    print("Heartbeat updated successfully.")

    # クールダウン状態の確認
    cooldown_path = Path("scratch/cooldown_state.json")
    if not cooldown_path.exists():
        print("COOLDOWN_INACTIVE: No cooldown state file found.")
        sys.exit(0)

    with open(cooldown_path, "r", encoding="utf-8") as f:
        cooldown_data = json.load(f)

    if not cooldown_data.get("cooldown_active", False):
        print("COOLDOWN_INACTIVE: Cooldown not active in state file.")
        sys.exit(0)

    reset_timestamp = cooldown_data.get("reset_timestamp", 0)
    current_time = time.time()
    
    status = hub.generate_flash_status()
    print("\n=== CURRENT FLASH STATUS ===")
    print(status.get("formatted", ""))
    print("============================\n")

    if current_time < reset_timestamp:
        remaining = int(reset_timestamp - current_time)
        rem_min = remaining // 60
        rem_sec = remaining % 60
        print(f"COOLDOWN_ACTIVE: Still cooling down. Quota resets in {rem_min}m {rem_sec}s (at {cooldown_data['reset_time_str']}).")
        print("ACTION: Sleep again for 900 seconds.")
        sys.exit(0)
    else:
        print("COOLDOWN_EXPIRED: Quota limit has been reset!")
        print("ACTION: Ready to re-spawn subagents and resume task execution.")
        
        # クールダウン状態の無効化
        cooldown_data["cooldown_active"] = False
        with open(cooldown_path, "w", encoding="utf-8") as f:
            json.dump(cooldown_data, f, ensure_ascii=False, indent=2)
        sys.exit(2)  # 特殊なリターンコードで expired を示す

if __name__ == "__main__":
    main()
