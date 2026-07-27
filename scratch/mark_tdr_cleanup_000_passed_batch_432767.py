import json
import os
import sys

state_path = r"C:\Users\PC_User\.gemini\antigravity\brain\457c82a1-5313-4128-b7c6-e40352f3cb52\scratch\flash_loop_state.json"

if not os.path.exists(state_path):
    print("State file not found.")
    sys.exit(1)

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

target_task_id = "T-batch_432767-tdr_cleanup-000"
message = "phase1_full_processing.py の run_ffmpeg_with_retry 関数に存在していた技術負債 TD-487 (except Exception) について、具体的な例外型 (SubprocessError, OSError, ValueError) に絞り込むリファクタリングを完了し、台帳およびレジストリを解消済みに更新しました。"
changed_files = [
    "backend/phase1_full_processing.py",
    "backend/agents/memory/technical_debt_index.json",
    "backend/TECHNICAL_DEBT_REGISTRY.md"
]

modified = False
for task in state.get("tasks", []):
    if task["id"] == target_task_id:
        task["status"] = "passed"
        task["result_report"] = {
            "message": message,
            "changed_files": changed_files
        }
        modified = True
        print(f"Updated local task {target_task_id} as passed.")

if modified:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    print("Local state file updated.")
else:
    print("Task not found in local state.")

# Update OrchestrationHub
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("backend"))
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
hub.register_flash_conversation_id("135ab72b-6f7c-4656-b1be-362c8f5e2ab7")
hub.flash_update_heartbeat()

report = {
    "message": message,
    "changed_files": changed_files
}
print(f"Marking hub task {target_task_id} as pass...")
hub.mark_task_done(target_task_id, "pass", report)
print("Hub task marked successfully.")

# Update parent heartbeat
hub = OrchestrationHub()
hub.register_flash_conversation_id("457c82a1-5313-4128-b7c6-e40352f3cb52")
hub.flash_update_heartbeat()
print("Parent heartbeat updated.")
