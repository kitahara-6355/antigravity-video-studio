import os
import shutil
import subprocess
from pathlib import Path

def main():
    project_root = Path(r"c:\Users\PC_User\Desktop\script\video-automation")
    brain_root = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\065194c8-04f3-4708-9c18-94ccadff1f41")
    
    # 1. Sources in subagent worktrees
    src_mark_task_helper = brain_root / ".system_generated" / "worktrees" / "subagent-test-weaver-Agent-self-a6721993" / "tests" / "test_mark_task_helper.py"
    src_dispatch_tasks = brain_root / ".system_generated" / "worktrees" / "subagent-test-weaver-Agent-self-4245dcc8" / "tests" / "test_dispatch_tasks.py"
    
    # 2. Find target locations in workspace (recursive scan project_root)
    dest_mark_task_helper = None
    dest_dispatch_tasks = None
    
    for path in project_root.rglob("*.py"):
        if ".system_generated" in path.parts or ".git" in path.parts or "venv" in path.parts:
            continue
        if path.name == "test_mark_task_helper.py":
            dest_mark_task_helper = path
        elif path.name == "test_dispatch_tasks.py":
            dest_dispatch_tasks = path
            
    print(f"Detected destinations:")
    print(f"  test_mark_task_helper.py: {dest_mark_task_helper}")
    print(f"  test_dispatch_tasks.py: {dest_dispatch_tasks}")
    
    if not dest_mark_task_helper:
        dest_mark_task_helper = project_root / "tests" / "test_mark_task_helper.py"
    if not dest_dispatch_tasks:
        dest_dispatch_tasks = project_root / "tests" / "test_dispatch_tasks.py"

    # 3. Perform copy
    if src_mark_task_helper.exists():
        print(f"Copying {src_mark_task_helper.name} to {dest_mark_task_helper}...")
        dest_mark_task_helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_mark_task_helper, dest_mark_task_helper)
        print("Copy success.")
    else:
        print(f"Source not found: {src_mark_task_helper}")
        
    if src_dispatch_tasks.exists():
        print(f"Copying {src_dispatch_tasks.name} to {dest_dispatch_tasks}...")
        dest_dispatch_tasks.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_dispatch_tasks, dest_dispatch_tasks)
        print("Copy success.")
    else:
        print(f"Source not found: {src_dispatch_tasks}")
        
    # 4. Run pytest validations
    print("\nValidating test_mark_task_helper.py...")
    res1 = subprocess.run(
        ["pytest", str(dest_mark_task_helper), "--timeout=300"],
        capture_output=True, text=True
    )
    print(res1.stdout)
    if res1.returncode == 0:
        print("test_mark_task_helper validation: PASS")
    else:
        print("test_mark_task_helper validation: FAIL")
        print(res1.stderr)
        
    print("\nValidating test_dispatch_tasks.py...")
    res2 = subprocess.run(
        ["pytest", str(dest_dispatch_tasks), "--timeout=300"],
        capture_output=True, text=True
    )
    print(res2.stdout)
    if res2.returncode == 0:
        print("test_dispatch_tasks validation: PASS")
    else:
        print("test_dispatch_tasks validation: FAIL")
        print(res2.stderr)

if __name__ == "__main__":
    main()
