import sys
import os
import shutil
import subprocess

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import cleanup_disk

def check_disk_space():
    total, used, free = shutil.disk_usage("C:\\")
    print(f"--- Disk Space (C:) ---")
    print(f"Total: {total / (1024**3):.2f} GB")
    print(f"Used : {used / (1024**3):.2f} GB")
    print(f"Free : {free / (1024**3):.2f} GB")

def run_git_worktree_prune():
    print("--- Git Worktree Status ---")
    try:
        res = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, check=True)
        print("Worktree list:")
        print(res.stdout)
    except Exception as e:
        print("Error listing worktrees:", e)
        
    try:
        print("Running git worktree prune...")
        subprocess.run(["git", "worktree", "prune"], check=True)
        print("Git worktree prune completed.")
    except Exception as e:
        print("Error pruning worktrees:", e)

def main():
    check_disk_space()
    
    # ディスクのクリーンアップスクリプトを呼び出す
    # 現在の会話IDなどを保護リストに指定
    active = {
        "851baf17-cfa5-4c9f-b4d2-9647773dc645"  # 現在のFlashセッション
    }
    
    print("Running cleanup_disk.main with keep_days=0...")
    cleanup_disk.main(active_ids=active, keep_days=0)
    
    run_git_worktree_prune()
    
    check_disk_space()

if __name__ == '__main__':
    main()
