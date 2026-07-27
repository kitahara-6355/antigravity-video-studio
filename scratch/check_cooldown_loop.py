import sys
import os
import subprocess
import time
from pathlib import Path

sys.path.append('.')
sys.path.append('backend')
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 自身の conversation ID を登録
    hub.register_flash_conversation_id("ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1")
    
    # 心拍更新 (最優先、STALE防止)
    hub.flash_update_heartbeat()
    print("Heartbeat updated successfully.")
    
    # cooldown_handler を実行して判定
    cooldown_script = Path("scratch/cooldown_handler.py")
    res = subprocess.run([sys.executable, str(cooldown_script)], capture_output=True, text=True)
    print(res.stdout)
    if res.stderr:
        print("Error from cooldown_handler:", res.stderr, file=sys.stderr)
        
    code = res.returncode
    if code == 2:
        print("COOLDOWN_EXPIRED_SIGNAL: Ready to resume!")
        # 呼び出し元(Antigravity)に復帰を促すため、特殊な戻りコード 2 で終了する
        sys.exit(2)
    else:
        # まだクールダウン中
        sys.exit(0)

if __name__ == "__main__":
    main()
