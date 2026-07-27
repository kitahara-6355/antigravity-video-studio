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
    wt_bughunter0 = r"C:\Users\PC_User\.gemini\antigravity\brain\819c8bbd-e916-476d-b8a1-8582dedb4659\.system_generated\worktrees\subagent-bug-hunter-Agent-self-b4f0b556"
    wt_refactor0 = r"C:\Users\PC_User\.gemini\antigravity\brain\819c8bbd-e916-476d-b8a1-8582dedb4659\.system_generated\worktrees\subagent-refactor-Agent-self-c4d72dba"
    
    files_to_copy = [
        (wt_bughunter0, "backend/scratch/check_worktree_git.py", "backend/scratch/check_worktree_git.py"),
        (wt_bughunter0, "backend/tests/test_scratch_check_worktree_git.py", "backend/tests/test_scratch_check_worktree_git.py"),
        (wt_refactor0, "backend/verify_full_system.py", "backend/verify_full_system.py"),
        (wt_refactor0, "backend/tests/test_verify_full_system.py", "backend/tests/test_verify_full_system.py")
    ]

    for wt_path, src_rel, dest_rel in files_to_copy:
        src_path = os.path.join(wt_path, src_rel)
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
