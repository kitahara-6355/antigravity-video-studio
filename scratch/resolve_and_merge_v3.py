import sys
import os
import subprocess
import json
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.agents.memory.technical_debt import TechnicalDebtStore

def run_cmd(cmd, cwd=None):
    print(f"[{cwd or '.'}] Running: {cmd}")
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    if res.returncode != 0:
        print(f"Error output:\n{res.stderr}")
    return res.returncode == 0, res.stdout, res.stderr

def load_json_from_branch(branch, file_path, cwd):
    # git show branch:file_path
    ok, stdout, _ = run_cmd(f"git show {branch}:{file_path}", cwd=cwd)
    if ok:
        try:
            return json.loads(stdout)
        except Exception as e:
            print(f"Failed to parse JSON from {branch}:{file_path}: {e}")
    return None

def merge_tdr_json_files(parent_json, branch_json):
    """
    2つの TDR json データを論理マージする
    """
    # entries のマージ (debt_idをキーにする)
    entries_map = {e["debt_id"]: e for e in parent_json.get("entries", [])}
    for e in branch_json.get("entries", []):
        debt_id = e["debt_id"]
        if debt_id not in entries_map:
            entries_map[debt_id] = e
        else:
            # 既に存在する場合、statusがfixedになっている方など、更新されている方を優先
            existing = entries_map[debt_id]
            if e["status"] == "fixed" and existing["status"] == "open":
                entries_map[debt_id] = e
            elif e["status"] != "open" and existing["status"] == "open":
                entries_map[debt_id] = e
                
    parent_json["entries"] = sorted(list(entries_map.values()), key=lambda x: x["debt_id"])
    parent_json["entry_count"] = len(parent_json["entries"])
    
    # changelog のマージ
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
    # 1. 競合したインデックスファイルのマージ
    parent_file = "backend/agents/memory/technical_debt_index.json"
    
    # マージ元(branch)のJSONデータを取得
    branch_json = load_json_from_branch(branch_name, parent_file, parent_dir)
    if not branch_json:
        print(f"Could not load JSON from branch {branch_name}")
        return False
        
    # 親(HEAD)のJSONデータを取得
    head_json = load_json_from_branch("HEAD", parent_file, parent_dir)
    if not head_json:
        # HEADから読めない場合はローカルのファイルから直接読む
        with open(os.path.join(parent_dir, parent_file), "r", encoding="utf-8") as f:
            head_json = json.load(f)
            
    # マージを実行
    merged_json = merge_tdr_json_files(head_json, branch_json)
    
    # マージ競合を一旦解消 (oursで上書き)
    run_cmd(f"git checkout --ours {parent_file} backend/TECHNICAL_DEBT_REGISTRY.md", cwd=parent_dir)
    
    # マージ結果を保存
    parent_file_path = os.path.join(parent_dir, parent_file)
    with open(parent_file_path, "w", encoding="utf-8") as f:
        json.dump(merged_json, f, ensure_ascii=False, indent=2)
        
    # TDR APIを使ってMarkdownファイルを再生成・保存
    store = TechnicalDebtStore(debt_dir=Path(parent_dir) / "backend/agents/memory")
    store._save()
    
    # git add
    run_cmd(f"git add {parent_file} backend/TECHNICAL_DEBT_REGISTRY.md", cwd=parent_dir)
    return True

def process_task(task_id, branch_name, worktree_dir, test_cmd, changed_files, parent_dir):
    print(f"\n==================== Processing {task_id} ====================")
    
    # 1. worktreeでgit add & commit
    _, status_out, _ = run_cmd("git status --porcelain", cwd=worktree_dir)
    if status_out.strip():
        ok, _, _ = run_cmd("git add .", cwd=worktree_dir)
        if not ok:
            return False
        ok, _, _ = run_cmd(f'git commit -m "Committed by parent for {task_id}"', cwd=worktree_dir)
        if not ok:
            return False
        print(f"Committed changes in worktree: {worktree_dir}")
        
    # 2. 親リポジトリでマージ
    # 競合を許容するために --no-commit を指定
    ok, stdout, stderr = run_cmd(f"git merge {branch_name} --no-commit --no-ff", cwd=parent_dir)
    if not ok:
        print(f"Merge encountered conflict as expected. Resolving conflicts...")
        # 競合解決プロセス
        resolved = resolve_tdr_conflict_and_merge(branch_name, parent_dir)
        if not resolved:
            run_cmd("git merge --abort", cwd=parent_dir)
            return False
            
    # コミットを完了させる
    run_cmd('git commit --no-edit', cwd=parent_dir)
    print(f"Successfully merged {branch_name} into parent branch.")
    
    # 3. テストを実行
    from backend.agents.orchestration import OrchestrationHub
    hub = OrchestrationHub()
    
    test_ok, t_stdout, t_stderr = run_cmd(test_cmd, cwd=parent_dir)
    if test_ok:
        print(f"Test passed for {task_id}.")
        hub.mark_task_done(task_id, "pass", {
            "message": f"Successfully stashed, merged {branch_name} and verified test.",
            "changed_files": changed_files
        })
        print(f"Marked {task_id} as DONE (pass).")
        return True
    else:
        print(f"Test failed for {task_id}. Rolling back merge...")
        run_cmd("git reset --hard HEAD~1", cwd=parent_dir)
        hub.mark_task_done(task_id, "fail", {
            "error": f"Test verification failed for command: {test_cmd}",
            "traceback": t_stdout + "\n" + t_stderr,
            "changed_files": []
        })
        print(f"Marked {task_id} as DONE (fail) and rolled back.")
        return False

# メイン処理
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 1. 親リポジトリでメタデータ変更をstash
print("Stashing parent changes...")
run_cmd("git stash -u", cwd=parent_dir)

try:
    # T-batch_41d3c0-test_weaver-000
    process_task(
        task_id="T-batch_41d3c0-test_weaver-000",
        branch_name="subagent-test-weaver-Agent-0-self-44995c3c",
        worktree_dir="C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-test-weaver-Agent-0-self-44995c3c",
        test_cmd="pytest backend/tests/test_init_check_robustness.py --timeout=300",
        changed_files=["backend/tests/test_init_check_robustness.py"],
        parent_dir=parent_dir
    )
    
    # T-batch_41d3c0-tdr_cleanup-000
    process_task(
        task_id="T-batch_41d3c0-tdr_cleanup-000",
        branch_name="subagent-tdr-cleanup-Agent-0-self-3ebb634e",
        worktree_dir="C:/Users/PC_User/.gemini/antigravity/brain/d0b2e390-7ede-4a78-983c-52d572664a7b/.system_generated/worktrees/subagent-tdr-cleanup-Agent-0-self-3ebb634e",
        test_cmd="pytest backend/tests/test_heartbeat_only.py --timeout=300",
        changed_files=["backend/agents/orchestration/heartbeat_only.py", "backend/tests/test_heartbeat_only.py"],
        parent_dir=parent_dir
    )

finally:
    # 復旧
    print("\nCleaning conflict-prone metadata files to allow safe stash pop...")
    run_cmd("git checkout -- backend/agents/memory/phase_state.json backend/agents/orchestration/flash_session.json backend/agents/orchestration/task_queue.json", cwd=parent_dir)
    print("Restoring stashed parent changes...")
    run_cmd("git stash pop", cwd=parent_dir)
