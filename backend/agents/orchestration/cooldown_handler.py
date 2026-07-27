import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# プロジェクトルートからのインポート
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.agents.orchestration import OrchestrationHub

def main():
    scratch_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\scratch")
    cooldown_file = scratch_dir / "cooldown_start.json"
    
    hub = OrchestrationHub()
    
    if not cooldown_file.exists():
        print("STATUS: NO_COOLDOWN")
        # 心拍は念のため更新しておく
        hub.flash_update_heartbeat()
        return
        
    try:
        with open(cooldown_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"STATUS: ERROR_READING_COOLDOWN - {e}")
        hub.flash_update_heartbeat()
        return

    reset_timestamp = data.get("reset_timestamp", 0)
    current_time = time.time()
    
    # 心拍の更新 (心拍レジリエンス規約に準拠)
    hub.flash_update_heartbeat()
    
    if current_time < reset_timestamp:
        remaining = int(reset_timestamp - current_time)
        print(f"STATUS: COOLDOWN_WAITING - remaining: {remaining}s")
    else:
        print("STATUS: COOLDOWN_FINISHED")
        # 完了したのでファイルを削除
        try:
            os.remove(cooldown_file)
        except OSError:
            pass

if __name__ == "__main__":
    main()
