import shutil
import os

def main():
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # test_weaver (8ab7cda2-93b1-44fb-a77e-a12337c262f7)
    wt_weaver = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-test-weaver-Agent-self-efe3c311"
    
    paths_to_try = [
        ("backend/tests/test_analyst.py", "backend/tests/test_analyst.py"),
        ("tests/test_analyst.py", "backend/tests/test_analyst.py")
    ]
    copied_weaver = False
    for rel_src, rel_dst in paths_to_try:
        src = os.path.join(wt_weaver, rel_src)
        dst = os.path.join(project_dir, rel_dst)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"Copied test_weaver: {src} to {dst}")
            copied_weaver = True
            break
    if not copied_weaver:
        print("Source test_analyst.py not found in worktree.")

    # refactor (d7274490-ce40-4b92-aae9-a82aa3d0dde2)
    wt_refactor = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-refactor-Agent-self-a24412b0"
    
    src_ref = os.path.join(wt_refactor, "backend/routers/admin_setup_router.py")
    dst_ref = os.path.join(project_dir, "backend/routers/admin_setup_router.py")
    if os.path.exists(src_ref):
        os.makedirs(os.path.dirname(dst_ref), exist_ok=True)
        shutil.copy2(src_ref, dst_ref)
        print(f"Copied refactor: {src_ref} to {dst_ref}")
    else:
        print(f"Source admin_setup_router.py not found: {src_ref}")

if __name__ == "__main__":
    main()
