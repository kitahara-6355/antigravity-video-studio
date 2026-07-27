import subprocess
import re
from pathlib import Path

current_session_id = "02e660a5-f119-464b-8073-81f4b664078b"
cwd = "C:/Users/PC_User/Desktop/script/video-automation"

try:
    # worktreeのリストを取得
    result = subprocess.run(["git", "worktree", "list"], capture_output=True, text=True, cwd=cwd, check=True)
    lines = result.stdout.strip().split("\n")
    
    deleted_count = 0
    for line in lines:
        if not line:
            continue
        # パス部分を取り出す (最初のスペースまで)
        match = re.match(r"^(\S+)", line)
        if match:
            path_str = match.group(1)
            # メインの作業ツリーは削除しない (cwdに一致するもの)
            if Path(path_str).resolve() == Path(cwd).resolve():
                continue
            
            # 現在のセッションIDを含むworktreeは削除しない
            if current_session_id in path_str:
                continue
            
            print(f"Removing worktree: {path_str}")
            try:
                subprocess.run(["git", "worktree", "remove", "--force", path_str], cwd=cwd, check=True)
                deleted_count += 1
            except Exception as e:
                print(f"Failed to remove {path_str}: {e}")
                
    print(f"Completed! Removed {deleted_count} worktrees.")
except Exception as e:
    print(f"Error: {e}")
