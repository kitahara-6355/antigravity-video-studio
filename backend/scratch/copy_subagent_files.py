# -*- coding: utf-8 -*-
import os
import shutil
import subprocess

worktrees_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\worktrees"
parent_dir = r"C:\Users\PC_User\Desktop\script\video-automation"

def find_matching_worktrees(base_dir: str, suffixes: list[str]) -> list[str]:
    """指定されたディレクトリからサフィックスにマッチするワークツリーのリストを探索します。"""
    if not os.path.exists(base_dir):
        return []
    
    try:
        subdirs = os.listdir(base_dir)
    except OSError as e:
        print(f"Error listing directory {base_dir}: {e}")
        return []
        
    matching_paths = []
    for subdir in subdirs:
        for suffix in suffixes:
            if subdir.endswith(suffix):
                matching_paths.append(os.path.join(base_dir, subdir))
                break
    return matching_paths

def get_changed_files(worktree_path: str) -> list[tuple[str, str]]:
    """指定されたワークツリー内で git status --porcelain を実行し、変更ファイルの相対パスとステータスのリストを取得します。"""
    try:
        git_result = subprocess.run(["git", "status", "--porcelain"], cwd=worktree_path, capture_output=True, text=True, check=True)
        stdout = git_result.stdout
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"Error running git status in {worktree_path}: {e}")
        return []
        
    changed_files = []
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        status_code = line[:2]
        file_rel_path = line[3:].strip()
        
        # クォーテーションされている場合は外す
        if file_rel_path.startswith('"') and file_rel_path.endswith('"'):
            file_rel_path = file_rel_path[1:-1]
            
        changed_files.append((file_rel_path, status_code))
    return changed_files

def filter_and_copy_files(worktree_path: str, changed_files: list[tuple[str, str]], dest_dir: str) -> None:
    """変更ファイルをフィルタリングし、指定された宛先ディレクトリへコピーします。"""
    for file_rel_path, status_code in changed_files:
        # 一時ディレクトリや除外対象
        if "temp_thumbnails" in file_rel_path or "content_dump.txt" in file_rel_path:
            continue
            
        src_file = os.path.join(worktree_path, file_rel_path)
        dst_file = os.path.join(dest_dir, file_rel_path)
        
        try:
            if os.path.isdir(src_file):
                continue
                
            print(f"  Copying: {file_rel_path} ({status_code})")
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
        except OSError as e:
            print(f"Error copying {file_rel_path} from {worktree_path} to {dest_dir}: {e}")

def main() -> None:
    """ワークツリーから変更差分ファイルを抽出し、親ディレクトリにコピーするメイン処理。"""
    if not os.path.exists(worktrees_dir):
        print("Worktrees directory not found.")
        return
        
    suffixes = ["2b52cbaf", "e2393d23", "27208bf9", "4389e589", "dfe8cd2f", "b5209376"]
    matching_worktrees = find_matching_worktrees(worktrees_dir, suffixes)
    
    print(f"Found {len(matching_worktrees)} matching worktrees:")
    for worktree in matching_worktrees:
        print(f"  {worktree}")
        
    for worktree in matching_worktrees:
        print(f"\nProcessing worktree: {os.path.basename(worktree)}")
        changed_files = get_changed_files(worktree)
        filter_and_copy_files(worktree, changed_files, parent_dir)
            
    print("\nCopy completed. Running fitness test to verify...")
    
if __name__ == "__main__":
    main()
