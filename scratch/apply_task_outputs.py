# -*- coding: utf-8 -*-
import sys
import os
import shutil
import subprocess

dest_root = r"c:\Users\PC_User\Desktop\script\video-automation"
wt_base_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\50f52326-96dd-4dec-8934-86d0eaf8e744\.system_generated\worktrees"

# (worktree_folder, task_id)
worktrees = [
    ("subagent-thumbnail-Agent-self-e448a032", "T-batch_f95bcd-thumbnail-000"),
    ("subagent-thumbnail-Agent-self-95c7013f", "T-batch_f95bcd-thumbnail-001"),
    ("subagent-test-weaver-Agent-self-b29c9f0e", "T-batch_f95bcd-test_weaver-000"),
    ("subagent-test-weaver-Agent-self-b2c80390", "T-batch_f95bcd-test_weaver-001"),
    ("subagent-bug-hunter-Agent-self-6efc0519", "T-batch_f95bcd-bug_hunter-000"),
    ("subagent-refactor-Agent-self-d687b4f5", "T-batch_f95bcd-refactor-000"),
]

def get_modified_files(wt_path):
    files = []
    # 1. Modified files
    try:
        out = subprocess.check_output(["git", "diff", "--name-only"], cwd=wt_path, text=True)
        files.extend([f.strip() for f in out.splitlines() if f.strip()])
    except Exception as e:
        print(f"Warning: git diff failed in {wt_path}: {e}")
        
    # 2. Untracked files
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], cwd=wt_path, text=True)
        for line in out.splitlines():
            if line.startswith("?? "):
                files.append(line[3:].strip())
            elif line.startswith(" M ") or line.startswith("A "):
                files.append(line[3:].strip())
    except Exception as e:
        print(f"Warning: git status failed in {wt_path}: {e}")
        
    return list(set(files))

def main():
    for folder, task_id in worktrees:
        wt_path = os.path.join(wt_base_dir, folder)
        if not os.path.exists(wt_path):
            print(f"Skipping {folder} (does not exist yet)")
            continue
            
        print(f"\n--- Processing {task_id} ({folder}) ---")
        modified = get_modified_files(wt_path)
        if not modified:
            print("No modified/new files found.")
            continue
            
        for rel_file in modified:
            # Skip python temporary files or artifacts that shouldn't be copied
            if rel_file.endswith(".pyc") or "__pycache__" in rel_file:
                continue
                
            src_file = os.path.join(wt_path, rel_file)
            # Ensure file exists (might have been deleted)
            if not os.path.exists(src_file):
                continue
                
            dest_file = os.path.join(dest_root, rel_file)
            print(f"Copying: {rel_file} -> {dest_file}")
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            shutil.copy2(src_file, dest_file)

if __name__ == "__main__":
    main()
