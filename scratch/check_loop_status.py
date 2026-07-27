import json
import os
from datetime import datetime, timezone

def check_status():
    phase_state_path = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\phase_state.json"
    flash_session_path = r"c:\Users\PC_User\Desktop\script\video-automation\backend\agents\orchestration\flash_session.json"
    
    if not os.path.exists(phase_state_path):
        print("RESTART: phase_state.json not found")
        return "RESTART"
        
    try:
        with open(phase_state_path, "r", encoding="utf-8") as f:
            phase_state = json.load(f)
    except Exception as e:
        print(f"RESTART: failed to load phase_state.json: {e}")
        return "RESTART"
        
    if phase_state.get("emergency_stop", False):
        print("STOP: emergency_stop is true")
        return "STOP"
        
    if not os.path.exists(flash_session_path):
        print("RESTART: flash_session.json not found")
        return "RESTART"
        
    try:
        with open(flash_session_path, "r", encoding="utf-8") as f:
            flash_session = json.load(f)
    except Exception as e:
        print(f"RESTART: failed to load flash_session.json: {e}")
        return "RESTART"
        
    status = flash_session.get("status")
    if status != "running":
        print(f"RESTART: status is '{status}' (not running)")
        return "RESTART"
        
    # Check heartbeat
    last_heartbeat_str = flash_session.get("last_heartbeat")
    if last_heartbeat_str:
        try:
            if last_heartbeat_str.endswith("Z"):
                last_heartbeat_str = last_heartbeat_str[:-1] + "+00:00"
            last_heartbeat = datetime.fromisoformat(last_heartbeat_str)
            now = datetime.now(timezone.utc)
            diff_seconds = (now - last_heartbeat).total_seconds()
            # heartbeatが20分(1200秒)以上古い場合はハングとみなす
            if diff_seconds > 1200:
                print(f"RESTART: last_heartbeat was {diff_seconds:.1f} seconds ago (hung)")
                return "RESTART"
        except Exception as e:
            print(f"WARNING: failed to parse heartbeat: {e}")
            
    print("RUNNING: Loop is running normally")
    return "RUNNING"

if __name__ == "__main__":
    check_status()
