import os
import subprocess
from pathlib import Path

def run_cmd(args, cwd):
    try:
        res = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def main():
    worktrees_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\316e6dfa-76e7-4c82-8418-c658b676d7df\.system_generated\worktrees")
    if not worktrees_dir.exists():
        print(f"Not found: {worktrees_dir}")
        return
        
    for path in worktrees_dir.iterdir():
        if path.is_dir():
            print(f"\n=========================================")
            print(f"Worktree: {path.name}")
            print(f"=========================================")
            # git status --porcelain で変更されたファイルを調べる
            status = run_cmd(["git", "status", "--porcelain"], path)
            print("Modified/Untracked files:")
            print(status if status else "No changes")

if __name__ == "__main__":
    main()
