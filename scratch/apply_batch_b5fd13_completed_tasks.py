import shutil
import os

def main():
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # refactor (4093edc7-1680-4ede-a69f-6416f08ab5d9)
    wt_refactor = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-refactor-Agent-self-65f3b910"
    refactor_files = [
        "backend/scratch/copy_subagent_files.py",
        "backend/tests/test_scratch_copy_subagent_files.py"
    ]
    for f in refactor_files:
        src = os.path.join(wt_refactor, f)
        dst = os.path.join(project_dir, f)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"Copied refactor: {src} to {dst}")
        else:
            print(f"Refactor src not found: {src}")

    # test_weaver (2d1cd05a-c126-4669-b9c5-22af653dadab)
    wt_weaver = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-test-weaver-Agent-self-1af37db1"
    weaver_files = [
        "backend/tests/test_scratch_integration_test.py"
    ]
    for f in weaver_files:
        src = os.path.join(wt_weaver, f)
        dst = os.path.join(project_dir, f)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"Copied weaver: {src} to {dst}")
        else:
            print(f"Weaver src not found: {src}")

if __name__ == "__main__":
    main()
