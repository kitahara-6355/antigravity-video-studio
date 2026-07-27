import sys
import os
import shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.agents.orchestration import OrchestrationHub

def sync():
    # 1. 心拍更新
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

    # 2. パス定義
    subagent_wt = r"C:\Users\PC_User\.gemini\antigravity\brain\819c8bbd-e916-476d-b8a1-8582dedb4659\.system_generated\worktrees\subagent-test-weaver-Agent-self-eae5b820"
    
    files_to_copy = [
        ("backend/tests/usage_tracker/test_alert_system.py", "backend/tests/usage_tracker/test_alert_system.py")
    ]

    for src_rel, dest_rel in files_to_copy:
        src_path = os.path.join(subagent_wt, src_rel)
        dest_path = os.path.join(r"C:\Users\PC_User\Desktop\script\video-automation", dest_rel)
        
        # フォルダの自動作成
        dest_dir = os.path.dirname(dest_path)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
            
        if os.path.exists(src_path):
            shutil.copy2(src_path, dest_path)
            print(f"Copied {src_path} to {dest_path}")
        else:
            print(f"Source file not found: {src_path}")

if __name__ == "__main__":
    sync()
