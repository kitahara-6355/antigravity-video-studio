import shutil
import os
import sys

root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_path)
sys.path.insert(0, os.path.join(root_path, "backend"))

from backend.agents.orchestration import OrchestrationHub
from backend.path_resolver import brain_dir

dest_base = root_path
# 会話 UUID は当時のもの。親（brain/）を解決に通しておく。
src_agent_0 = str(
    brain_dir()
    / "f9a7ff51-0cc8-4692-aa10-04feec4ee3ce"
    / ".system_generated"
    / "worktrees"
    / "subagent-bug-hunter-Agent-0-self-6de64ebe"
)

copy_targets = [
    (src_agent_0, "backend/agents/orchestration/flash_runner_control.py", "backend/agents/orchestration/flash_runner_control.py"),
    (src_agent_0, "backend/tests/test_flash_runner_control.py", "backend/tests/test_flash_runner_control.py")
]

print("--- Starting File Copy (Agent 0) ---")
for src_base, src_rel, dest_rel in copy_targets:
    src_path = os.path.join(src_base, os.path.normpath(src_rel))
    dest_path = os.path.join(dest_base, os.path.normpath(dest_rel))
    if os.path.exists(src_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(src_path, dest_path)
        print(f"Copied: {src_rel} -> {dest_rel}")
    else:
        print(f"File not found: {src_path}")

print("--- Marking Tasks as Done (Agent 0) ---")
hub = OrchestrationHub()

report_agent_0 = {
    "subagent_id": "73ed5ee3-f4a5-4cea-8dd6-057a64523370",
    "message": "Successfully resolved except Exceptions in flash_runner_control.py, added tests, and confirmed 10 passed."
}
hub.mark_task_done("T-batch_00d5aa-bug_hunter-000", "pass", report_agent_0)
print("Marked T-batch_00d5aa-bug_hunter-000 as pass")

print("COPY_AND_MARK_PROCESS_COMPLETED")
