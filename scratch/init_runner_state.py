import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
queue_status = hub.get_queue_status()
batch_id = queue_status["batch_id"]

if not batch_id:
    print("エラー: バッチIDが見つかりません。")
    sys.exit(1)

# キューから現在のアクティブなタスクリスト（あるいはタスクの定義）を取得する。
# orchestrator.py の実装から、現在実行中のタスクを特定するために、
# task_queue.json などの内部ファイルを読むか、OrchestrationHub の
# バッチ取得で得られた最新リストからマッピングします。
# 幸い、try_get_batch.pyでバッチは取得されています。
# task_queue.json の内容を読んで、状態を構築します。
task_queue_path = project_root / "backend/agents/orchestration/task_queue.json"
with open(task_queue_path, "r", encoding="utf-8") as f:
    queue_data = json.load(f)

tasks = {}
for task in queue_data.get("tasks", []):
    if task["status"] == "running":
        tasks[task["id"]] = {
            "task_id": task["id"],
            "group": task["group"],
            "target_module": task["target_module"],
            "instruction": task.get("instruction", ""),
            "status": "pending",
            "subagent_id": None,
            "result": None,
            "report": None
        }

state = {
    "batch_id": batch_id,
    "phase": queue_status["phase"],
    "milestone": queue_status["milestone"],
    "tasks": tasks,
    "completed_tasks_count": 0,
    "total_tasks_count": len(tasks)
}

state_path = project_root / "scratch/flash_runner_state.json"
state_path.parent.mkdir(parents=True, exist_ok=True)
with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"状態ファイルを初期化しました: {state_path}")
print(f"タスク件数: {len(tasks)}")
