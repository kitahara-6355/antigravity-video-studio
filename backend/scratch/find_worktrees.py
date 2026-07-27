import subprocess
import os
import sys
from typing import List

DEFAULT_CONV_ID = "a9736a64-a242-485f-942e-bf8476d21fa6"

class GitCommandError(RuntimeError):
    """Gitコマンドの実行に失敗した際のエラー。"""
    pass

def get_worktree_lines() -> List[str]:
    """Git worktreeの一覧を取得する。"""
    # satisfies: REQ-WTREE-01
    # satisfies: REQ-WTREE-02
    try:
        # フリーズ防止のため timeout=10 を設定
        res = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            raise GitCommandError(f"Git command failed: {res.stderr.strip()}", res.returncode)
        return res.stdout.splitlines()
    except FileNotFoundError as e:
        raise GitCommandError("Git command not found. Please install git.", 1) from e
    except subprocess.TimeoutExpired as e:
        raise GitCommandError("Git command timed out.", 1) from e

def find_matching_worktrees(lines: List[str], conv_id: str) -> List[str]:
    """与えられた会話IDに一致するworktree of linesをフィルタリングする。"""
    return [l for l in lines if conv_id in l]

def main() -> None:
    conv_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONV_ID
    try:
        lines = get_worktree_lines()
        print(f"Total worktrees: {len(lines)}")
        
        matching = find_matching_worktrees(lines, conv_id)
        print(f"Found {len(matching)} matching worktrees:")
        for m in matching:
            print(m)
    except GitCommandError as e:
        # エラーメッセージをsys.stderrに出力して終了する
        msg, code = e.args
        print(msg, file=sys.stderr)
        sys.exit(code)

if __name__ == "__main__":
    main()



