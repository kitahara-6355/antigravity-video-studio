import shutil
import os

def main():
    wt_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-bug-hunter-Agent-self-bfff86b1"
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # 1. Copy copy_artifacts2.py
    src_prod = os.path.join(wt_dir, "backend/agents/orchestration/copy_artifacts2.py")
    dst_prod = os.path.join(project_dir, "backend/agents/orchestration/copy_artifacts2.py")
    if os.path.exists(src_prod):
        os.makedirs(os.path.dirname(dst_prod), exist_ok=True)
        shutil.copy2(src_prod, dst_prod)
        print(f"Copied {src_prod} to {dst_prod}")
    else:
        print(f"Source file not found: {src_prod}")

    # 2. Copy test_copy_artifacts2.py
    paths_to_try = [
        ("backend/tests/test_copy_artifacts2.py", "backend/tests/test_copy_artifacts2.py"),
        ("tests/test_copy_artifacts2.py", "backend/tests/test_copy_artifacts2.py")
    ]

    copied = False
    for rel_src, rel_dst in paths_to_try:
        src = os.path.join(wt_dir, rel_src)
        dst = os.path.join(project_dir, rel_dst)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"Copied {src} to {dst}")
            copied = True
            break
            
    if not copied:
        print("Source test_copy_artifacts2.py not found in worktree.")

if __name__ == "__main__":
    main()
