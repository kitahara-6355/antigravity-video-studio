import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

# 今回の第11バッチ (batch_37f044) のマッピング定義
mapping = {
    "T-batch_37f044-thumbnail-000": "11a92f89-056b-4d47-9cc5-7be747714c4a",
    "T-batch_37f044-thumbnail-001": "ed587834-048e-4548-b73b-c7e1294da715",
    "T-batch_37f044-thumbnail-002": "b1f0999c-f181-4324-826d-577da18e46c2",
    "T-batch_37f044-thumbnail-003": "d406920d-fa55-4a6c-82c0-d5494d4b40e4",
    "T-batch_37f044-thumbnail-004": "d5989732-2d0c-4350-99b5-662f51d94742",
    "T-batch_37f044-thumbnail-005": "aed2ff10-893c-4632-8ada-77b9e50efb7c"
}





state_path = project_root / "scratch/flash_runner_state.json"
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

for task_id, subagent_id in mapping.items():
    if task_id in state["tasks"]:
        state["tasks"][task_id]["subagent_id"] = subagent_id
        state["tasks"][task_id]["status"] = "running"

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

# OrchestrationHub側のセッションステータスも更新する
hub = OrchestrationHub()
batch_id = state["batch_id"]
hub.flash_update_status(
    activity="executing",
    step=f"バッチ {batch_id}: 6タスク実行中 (サブエージェント並行稼働)",
    batch_id=batch_id,
    subagents_running=6
)

print("第11バッチの状態ファイルおよびOrchestrationHubを更新しました。")




