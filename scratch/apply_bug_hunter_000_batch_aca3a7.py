import shutil
import os

src_worktree = "C:/Users/PC_User/.gemini/antigravity/brain/ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1/.system_generated/worktrees/subagent-bug-hunter-Agent-000-self-fb634a47"
dest_root = "c:/Users/PC_User/Desktop/script/video-automation"

files_to_copy = [
    "backend/agents/orchestration/wave_scheduler.py",
    "backend/tests/test_wave_scheduler.py",
    "pytest.ini"
]

for rel_path in files_to_copy:
    src_file = os.path.join(src_worktree, rel_path)
    dest_file = os.path.join(dest_root, rel_path)
    if os.path.exists(src_file):
        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
        shutil.copy2(src_file, dest_file)
        print(f"Copied: {rel_path}")
    else:
        print(f"Warning: Source file not found: {src_file}")
