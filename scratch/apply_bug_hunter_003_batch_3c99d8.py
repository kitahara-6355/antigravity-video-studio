import shutil
import sys
import os

src_worktree = r"C:\Users\PC_User\.gemini\antigravity\brain\f9a7ff51-0cc8-4692-aa10-04feec4ee3ce\.system_generated\worktrees\subagent-bug-hunter-Agent-3-self-6c9fff8f"
dest_root = r"C:\Users\PC_User\Desktop\script\video-automation"

files_to_copy = [
    "backend/agents/orchestration/run_batch_report.py",
    "tests/test_run_batch_report.py",
    "pytest.ini"
]

for rel_path in files_to_copy:
    src_file = os.path.join(src_worktree, rel_path)
    dest_file = os.path.join(dest_root, rel_path)
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    print(f"Copying {src_file} -> {dest_file}")
    shutil.copy2(src_file, dest_file)

sys.path.insert(0, dest_root)
sys.path.insert(0, os.path.join(dest_root, "backend"))
from backend.agents.orchestration import OrchestrationHub
hub = OrchestrationHub()
hub.register_flash_conversation_id("f9a7ff51-0cc8-4692-aa10-04feec4ee3ce")

report = {
    "message": "except Exception を具体的な例外型に置換。テスト4件を追加し、pytest.ini のパスを更新。",
    "changed_files": files_to_copy
}

hub.mark_task_done("T-batch_3c99d8-bug_hunter-003", "pass", report)
print("Task T-batch_3c99d8-bug_hunter-003 marked as completed.")
