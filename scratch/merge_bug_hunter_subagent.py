import os
import shutil

src_worktree = r"C:\Users\PC_User\.gemini\antigravity\brain\065194c8-04f3-4708-9c18-94ccadff1f41\.system_generated\worktrees\subagent-bug-hunter-Agent-self-75d76e69"
dest_root = r"c:\Users\PC_User\Desktop\script\video-automation"

# Target files to copy
targets = [
    ("backend/routers/segments.py", "backend/routers/segments.py"),
    ("backend/tests/test_segments_router.py", "backend/tests/test_segments_router.py"),
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
