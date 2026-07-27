import shutil
import os

def main():
    project_dir = r"c:\Users\PC_User\Desktop\script\video-automation"

    # refactor subagent
    wt_refactor = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-refactor-Agent-self-e9d608db"
    refactor_files = [
        "backend/utils/evolution_log_migration.py",
        "backend/agents/memory/technical_debt_index.json",
        "backend/TECHNICAL_DEBT_REGISTRY.md"
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

    # test_weaver subagent (8a0dbd28-4756-475e-beca-23f162077390)
    wt_weaver = r"C:\Users\PC_User\.gemini\antigravity\brain\d040406a-753e-4388-b488-b525cd358e85\.system_generated\worktrees\subagent-test-weaver-Agent-self-db67804e"
    
    weaver_files = [
        "backend/tests/test_phase_a_telops_srt.py"
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
