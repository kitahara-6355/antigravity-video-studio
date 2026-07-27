import os
import shutil

src_worktree = r"C:\Users\PC_User\.gemini\antigravity\brain\1cb1b227-bfb2-47e8-bb50-89535ef278ff\.system_generated\worktrees\subagent-thumbnail-Agent-self-a54ddf92"
dest_root = r"c:\Users\PC_User\Desktop\script\video-automation"

# Target files to copy
targets = [
    ("backend/project_archiver.py", "backend/project_archiver.py"),
    ("backend/tests/test_project_archiver_thumbnail.py", "backend/tests/test_project_archiver_thumbnail.py"),
]

for src_rel, dest_rel in targets:
    src_path = os.path.join(src_worktree, src_rel)
    dest_path = os.path.join(dest_root, dest_rel)
    
    if os.path.exists(src_path):
        print(f"Copying {src_path} -> {dest_path}")
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(src_path, dest_path)
    else:
        print(f"Source file not found: {src_path}")
