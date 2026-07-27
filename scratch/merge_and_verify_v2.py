import sys
import os
import subprocess
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()

def run_cmd(cmd, cwd=None):
    print(f"[{cwd or '.'}] Running: {cmd}")
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    if res.returncode != 0:
        print(f"Error output:\n{res.stderr}")
    return res.returncode == 0, res.stdout, res.stderr

def merge_and_verify_with_stash(tasks):
    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # 1. 親リポジトリで git stash を実行してローカル変更を退避
    print("Stashing parent changes...")
    stashed, _, _ = run_cmd("git stash -u", cwd=parent_dir)
    
    try:
        for t in tasks:
            task_id = t["task_id"]
            branch_name = t["branch_name"]
            worktree_dir = t["worktree_dir"]
            test_cmd = t["test_cmd"]
            changed_files = t["changed_files"]
            
            print(f"\n==================== Processing {task_id} ====================")
            
            # worktreeでgit add & commit
            _, status_out, _ = run_cmd("git status --porcelain", cwd=worktree_dir)
            if status_out.strip():
                ok, _, _ = run_cmd("git add .", cwd=worktree_dir)
                if not ok:
                    print(f"Failed to git add in {worktree_dir}")
                    continue
                ok, _, _ = run_cmd(f'git commit -m "Committed by parent for {task_id}"', cwd=worktree_dir)
                if not ok:
                    print(f"Failed to git commit in {worktree_dir}")
                    continue
                print(f"Committed changes in worktree: {worktree_dir}")
            else:
                print(f"No changes to commit in worktree: {worktree_dir}")
            
            # マージを実行
            ok, stdout, stderr = run_cmd(f"git merge {branch_name} --no-edit", cwd=parent_dir)
            if not ok:
                print(f"Failed to merge {branch_name} into parent. Aborting merge...")
                run_cmd("git merge --abort", cwd=parent_dir)
                continue
            print(f"Successfully merged {branch_name} into parent branch.")
            
            # テストを実行
            test_ok, t_stdout, t_stderr = run_cmd(test_cmd, cwd=parent_dir)
            if test_ok:
                print(f"Test passed for {task_id}.")
                hub.mark_task_done(task_id, "pass", {
                    "message": f"Successfully stashed, merged {branch_name} and verified test.",
                    "changed_files": changed_files
                })
                print(f"Marked {task_id} as DONE (pass).")
            else:
                print(f"Test failed for {task_id}. Rolling back merge...")
                run_cmd("git reset --hard HEAD~1", cwd=parent_dir)
                hub.mark_task_done(task_id, "fail", {
                    "error": f"Test verification failed for command: {test_cmd}",
                    "traceback": t_stdout + "\n" + t_stderr,
                    "changed_files": []
                })
                print(f"Marked {task_id} as DONE (fail) and rolled back.")
                
    finally:
        if stashed:
            print("Restoring stashed parent changes...")
            # stashした内容を pop して復元する
            # メタデータ競合が発生した場合はマージされる可能性があるため
            run_cmd("git stash pop", cwd=parent_dir)

# 処理対象
tasks_to_process = [
    {
        "task_id": "T-batch_41d3c0-test_weaver-000",
        "branch_name": "subagent-test-weaver-Agent-0-self-44995c3c",
        "worktree_dir": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-test-weaver-Agent-0-self-44995c3c",
        "test_cmd": "pytest backend/tests/test_init_check_robustness.py --timeout=300",
        "changed_files": ["backend/tests/test_init_check_robustness.py"]
    },
    {
        "task_id": "T-batch_41d3c0-test_weaver-001",
        "branch_name": "subagent-test-weaver-Agent-1-self-688fcda1",
        "worktree_dir": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-test-weaver-Agent-1-self-688fcda1",
        "test_cmd": "pytest tests/test_scratch_get_next_batch.py --timeout=300",
        "changed_files": ["tests/test_scratch_get_next_batch.py"]
    },
    {
        "task_id": "T-batch_41d3c0-bug_hunter-001",
        "branch_name": "subagent-bug-hunter-Agent-1-self-7aafc214",
        "worktree_dir": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-bug-hunter-Agent-1-self-7aafc214",
        "test_cmd": "pytest backend/tests/test_smartcut_thumbnail.py backend/tests/test_shared/test_smartcut_router.py backend/tests/test_shared/test_cov_smartcut_trinity.py --timeout=300",
        "changed_files": ["backend/routers/smartcut.py", "backend/tests/test_smartcut_thumbnail.py"]
    }
]

merge_and_verify_with_stash(tasks_to_process)
