import json
import os
import sys

state_path = r"C:\Users\PC_User\.gemini\antigravity\brain\457c82a1-5313-4128-b7c6-e40352f3cb52\scratch\flash_loop_state.json"

if not os.path.exists(state_path):
    print("State file not found.")
    sys.exit(1)

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

target_task_id = "T-batch_432767-test_weaver-003"
message = "copy_artifacts_batch_00d5aa_agent0.py に対し、コピー元ファイルが一部のみ存在する状態で存在するファイルだけがコピーされる混合ケースを検証するテストを追加し、堅牢性を向上させました。"
changed_files = [
    "tests/test_copy_artifacts_batch_00d5aa_agent0.py"
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
hub.register_flash_conversation_id("755c53dd-876f-4fc0-822d-82af1bb8c6f6")
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
