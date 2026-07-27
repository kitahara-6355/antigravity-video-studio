import os
import sys
import subprocess
from pathlib import Path

def get_worktrees_dir():
    # スクリプトの絶対パスを取得し、親ディレクトリを辿って .system_generated/worktrees を自動検出
    current_file = Path(os.path.abspath(__file__))
    for parent in current_file.parents:
        if parent.name == "worktrees" or (parent / ".system_generated" / "worktrees").exists():
            if parent.name == "worktrees":
                return parent
            else:
                return parent / ".system_generated" / "worktrees"
    
    # フォールバック
    fallback = r"C:\Users\PC_User\.gemini\antigravity\brain\0723d652-a51c-45e1-a10b-442254c17079\.system_generated\worktrees"
    if os.path.exists(fallback):
        return Path(fallback)
    return None

def run_tests():
    print("\nRunning quality verification tests...")
    env = os.environ.copy()
    cwd = Path.cwd()
    env["PYTHONPATH"] = f"{cwd};{cwd}/backend;{env.get('PYTHONPATH', '')}"
    
    res = subprocess.run(
        ["pytest", "-v", "backend/tests/test_combined_overlay_thumbnail.py"],
        capture_output=True,
        text=True,
        env=env
    )
    print(res.stdout)
    if res.returncode != 0:
        print("STDERR:", res.stderr)
        return False
    return True

def main():
    worktrees_dir = get_worktrees_dir()
    if not worktrees_dir or not worktrees_dir.exists():
        print("Worktrees directory not found.")
        return
        
    print(f"Worktrees directory detected: {worktrees_dir}")
    print("Scanning worktrees for dynamic suffixes...")
    
    subdirs = os.listdir(worktrees_dir)
    branches_to_merge = []
    
    # 動的にワークツリーディレクトリ名から末尾の suffix (8文字の16進数) を抽出
    suffixes = set()
    for subdir in subdirs:
        if subdir.startswith("subagent-"):
            parts = subdir.split("-")
            if len(parts) >= 2:
                suffix = parts[-1]
                if len(suffix) == 8:
                    suffixes.add(suffix)
                    
    print(f"Detected suffixes to merge: {list(suffixes)}")
    
    for subdir in subdirs:
        branch_name = subdir
        for s in suffixes:
            if branch_name.endswith(s):
                branches_to_merge.append(branch_name)
                break
                
    branches_to_merge = sorted(list(set(branches_to_merge)))
    
    print(f"Found {len(branches_to_merge)} branches to merge:")
    for b in branches_to_merge:
        print(f"  {b}")
        
    # git merge 実行
    merged_count = 0
    failed_count = 0
    for b in branches_to_merge:
        print(f"\nMerging branch: {b} ...")
        res = subprocess.run(["git", "merge", "--no-edit", b], capture_output=True, text=True)
        print("STDOUT:", res.stdout)
        if res.returncode != 0:
            print(f"Merge failed for branch {b}. Aborting merge...")
            subprocess.run(["git", "merge", "--abort"])
            failed_count += 1
            continue
            
        # マージ後の品質テストを実行
        if not run_tests():
            print(f"Quality validation failed after merging {b}. Rolling back merge...")
            subprocess.run(["git", "reset", "--hard", "HEAD~1"])
            failed_count += 1
        else:
            print(f"Successfully merged and validated branch: {b}")
            merged_count += 1
            
    print(f"\nMerge summary: {merged_count} succeeded, {failed_count} failed.")

if __name__ == "__main__":
    main()
