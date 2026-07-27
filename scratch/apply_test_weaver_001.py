import shutil
import os

def main():
    wt_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-test-weaver-Agent-self-f02e07ca"
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # Try backend/tests first, then tests/
    paths_to_try = [
        ("backend/tests/test_sdk_checker.py", "backend/tests/test_sdk_checker.py"),
        ("tests/test_sdk_checker.py", "backend/tests/test_sdk_checker.py")
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
        print("Source test_sdk_checker.py not found in worktree.")

if __name__ == "__main__":
    main()
