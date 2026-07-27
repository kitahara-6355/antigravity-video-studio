import sys
import os
import subprocess
import json
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))
from backend.agents.memory.technical_debt import TechnicalDebtStore
from backend.agents.orchestration import OrchestrationHub

def run_cmd(cmd, cwd=None):
    print(f"[{cwd or '.'}] Running: {cmd}")
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    if res.returncode != 0:
        print(f"Error output:\n{res.stderr}")
    return res.returncode == 0, res.stdout, res.stderr

def load_json_from_branch(branch, file_path, cwd):
    ok, stdout, _ = run_cmd(f"git show {branch}:{file_path}", cwd=cwd)
    if ok:
        try:
            return json.loads(stdout)
        except Exception as e:
            print(f"Failed to parse JSON from {branch}:{file_path}: {e}")
    return None

def merge_tdr_json_files(parent_json, branch_json):
    entries_map = {e["debt_id"]: e for e in parent_json.get("entries", [])}
    for e in branch_json.get("entries", []):
        debt_id = e["debt_id"]
        if debt_id not in entries_map:
            entries_map[debt_id] = e
        else:
            existing = entries_map[debt_id]
            if e["status"] == "fixed" and existing["status"] == "open":
                entries_map[debt_id] = e
            elif e["status"] != "open" and existing["status"] == "open":
                entries_map[debt_id] = e
                
    parent_json["entries"] = sorted(list(entries_map.values()), key=lambda x: x["debt_id"])
    parent_json["entry_count"] = len(parent_json["entries"])
    
    changelog_map = {}
    for r in parent_json.get("changelog", []):
        key = (r["timestamp"], r["debt_id"], r["action"])
        changelog_map[key] = r
    for r in branch_json.get("changelog", []):
        key = (r["timestamp"], r["debt_id"], r["action"])
        changelog_map[key] = r
        
    parent_json["changelog"] = sorted(list(changelog_map.values()), key=lambda x: x["timestamp"])[-500:]
    parent_json["last_updated"] = branch_json.get("last_updated", parent_json.get("last_updated"))
    
    return parent_json

def resolve_tdr_conflict_and_merge(branch_name, parent_dir):
    parent_file = "backend/agents/memory/technical_debt_index.json"
    branch_json = load_json_from_branch(branch_name, parent_file, parent_dir)
    if not branch_json:
        return False
    head_json = load_json_from_branch("HEAD", parent_file, parent_dir)
    if not head_json:
        with open(os.path.join(parent_dir, parent_file), "r", encoding="utf-8") as f:
            head_json = json.load(f)
            
    merged_json = merge_tdr_json_files(head_json, branch_json)
    run_cmd(f"git checkout --ours {parent_file} backend/TECHNICAL_DEBT_REGISTRY.md", cwd=parent_dir)
    
    parent_file_path = os.path.join(parent_dir, parent_file)
    with open(parent_file_path, "w", encoding="utf-8") as f:
        json.dump(merged_json, f, ensure_ascii=False, indent=2)
        
    store = TechnicalDebtStore(debt_dir=Path(parent_dir) / "backend/agents/memory")
    store._save()
    
    run_cmd(f"git add {parent_file} backend/TECHNICAL_DEBT_REGISTRY.md", cwd=parent_dir)
    return True

# メイン処理
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

tasks = [
    {
        "id": "T-batch_bb4b29-thumbnail-001",
        "branch": "subagent-thumbnail-Agent-1-self-0ade0b56",
        "worktree": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-thumbnail-Agent-1-self-0ade0b56",
        "test_cmd": "python -m pytest backend/tests/test_thumbnail_generator.py --timeout=300",
        "files": ["backend/thumbnail_engine/generator.py"]
    },
    {
        "id": "T-batch_bb4b29-test_weaver-001",
        "branch": "subagent-test-weaver-Agent-1-self-88d9464d",
        "worktree": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-test-weaver-Agent-1-self-88d9464d",
        "test_cmd": "python -m pytest tests/test_model_guardian.py --timeout=300",
        "files": ["tests/test_model_guardian.py"]
    },
    {
        "id": "T-batch_bb4b29-test_weaver-000",
        "branch": "subagent-test-weaver-Agent-0-self-8bc4c46b",
        "worktree": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-test-weaver-Agent-0-self-8bc4c46b",
        "test_cmd": "python -m pytest tests/test_pipeline_report.py --timeout=300",
        "files": ["tests/test_pipeline_report.py"]
    },
    {
        "id": "T-batch_bb4b29-bug_hunter-001",
        "branch": "subagent-bug-hunter-Agent-1-self-d8ac0fef",
        "worktree": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-bug-hunter-Agent-1-self-d8ac0fef",
        "test_cmd": "python -m pytest tests/test_minimal_telop_generator.py --timeout=300",
        "files": ["backend/minimal_telop_generator.py"]
    },
    {
        "id": "T-batch_bb4b29-tdr_cleanup-000",
        "branch": "subagent-tdr-cleanup-Agent-0-self-51a29ff2",
        "worktree": "C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-tdr-cleanup-Agent-0-self-51a29ff2",
        "test_cmd": "python -m pytest tests/test_mark_tasks_p27_thumb1.py --timeout=300",
        "files": ["backend/agents/orchestration/mark_tasks_p27_thumb1.py"]
    }
]

print("Stashing parent changes...")
run_cmd("git stash -u", cwd=parent_dir)

success_tasks = []
fail_tasks = []

try:
    for task in tasks:
        task_id = task["id"]
        branch_name = task["branch"]
        worktree_dir = task["worktree"]
        test_cmd = task["test_cmd"]
        changed_files = task["files"]
        
        print(f"\n==================== Processing {task_id} ====================")
        
        # 1. worktreeでgit add & commit
        _, status_out, _ = run_cmd("git status --porcelain", cwd=worktree_dir)
        if status_out.strip():
            ok, _, _ = run_cmd("git add .", cwd=worktree_dir)
            if not ok:
                fail_tasks.append((task_id, {"error": "Failed to add files in worktree."}))
                continue
            ok, _, _ = run_cmd(f'git commit -m "Committed by parent for {task_id}"', cwd=worktree_dir)
            if not ok:
                fail_tasks.append((task_id, {"error": "Failed to commit in worktree."}))
                continue
            print(f"Committed changes in worktree: {worktree_dir}")
            
        # 2. 親リポジトリでマージ
        ok, stdout, stderr = run_cmd(f"git merge {branch_name} --no-commit --no-ff", cwd=parent_dir)
        if not ok:
            print(f"Merge encountered conflict. Resolving conflicts...")
            resolved = resolve_tdr_conflict_and_merge(branch_name, parent_dir)
            if not resolved:
                run_cmd("git merge --abort", cwd=parent_dir)
                fail_tasks.append((task_id, {"error": "Conflict resolution failed during merge."}))
                continue
                
        run_cmd('git commit --no-edit', cwd=parent_dir)
        print(f"Successfully merged {branch_name} into parent branch.")
        
        # 3. テストを実行
        test_ok, t_stdout, t_stderr = run_cmd(test_cmd, cwd=parent_dir)
        if test_ok:
            print(f"Test passed for {task_id}.")
            success_tasks.append((task_id, {
                "message": f"Successfully stashed, merged {branch_name} and verified test.",
                "changed_files": changed_files
            }))
        else:
            print(f"Test failed for {task_id}. Rolling back merge...")
            run_cmd("git reset --hard HEAD~1", cwd=parent_dir)
            fail_tasks.append((task_id, {
                "error": f"Test verification failed for command: {test_cmd}",
                "traceback": t_stdout + "\n" + t_stderr
            }))

finally:
    # 復旧
    print("\nCleaning conflict-prone metadata files to allow safe stash pop...")
    run_cmd("git checkout -- backend/agents/memory/phase_state.json backend/agents/orchestration/flash_session.json backend/agents/orchestration/task_queue.json", cwd=parent_dir)
    print("Restoring stashed parent changes...")
    run_cmd("git stash pop", cwd=parent_dir)

# 最後の最後に一括して mark_task_done を呼ぶ（git checkout/stash pop の影響を受けないようにするため）
print("\n=== Updating Task Status on OrchestrationHub ===")
hub = OrchestrationHub()
for task_id, report in success_tasks:
    hub.mark_task_done(task_id, "pass", report)
    print(f"Marked {task_id} as pass.")
for task_id, report in fail_tasks:
    hub.mark_task_done(task_id, "fail", report)
    print(f"Marked {task_id} as fail.")
