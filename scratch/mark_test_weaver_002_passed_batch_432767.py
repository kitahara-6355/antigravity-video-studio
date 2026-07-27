import json
import os
import sys

state_path = r"C:\Users\PC_User\.gemini\antigravity\brain\457c82a1-5313-4128-b7c6-e40352f3cb52\scratch\flash_loop_state.json"

if not os.path.exists(state_path):
    print("State file not found.")
    sys.exit(1)

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

target_task_id = "T-batch_432767-test_weaver-002"
message = "ux_verification/ratchet.py に対し、極端な値での初期化、マイナス連動率によるデルタ境界、充足率警告条件、および多様なレイヤー値での挙動など4つの頑健性テストを追加し、アサーションを補強しました。"
changed_files = [
    "backend/tests/test_ux_ratchet.py",
    "tests/test_ux_ratchet.py"
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
hub.register_flash_conversation_id("5f2f8dcd-fba7-438d-bbf3-b9ec773f7686")
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
