import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

if len(sys.argv) < 4:
    print("使用法: python handle_task_completion.py <task_id> <status> <report_json_str>")
    sys.exit(1)

task_id = sys.argv[1]
status = sys.argv[2]
report_str = sys.argv[3]

try:
    report = json.loads(report_str)
except Exception:
    report = {"message": report_str}

# 1. 状態ファイルを読み込む
state_path = project_root / "scratch/flash_runner_state.json"
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

# 2. タスクを更新
if task_id in state["tasks"]:
    state["tasks"][task_id]["status"] = status
    state["tasks"][task_id]["result"] = status
    state["tasks"][task_id]["report"] = report
else:
    print(f"警告: タスクID {task_id} が状態ファイルにありません。")

# 3. 完了数を再計算
completed = sum(1 for t in state["tasks"].values() if t["status"] in ("pass", "fail"))
state["completed_tasks_count"] = completed

# 状態ファイルを書き出す
with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

# 4. OrchestrationHub 側でタスク完了マーク
hub = OrchestrationHub()
hub.mark_task_done(task_id, status, report)

# 5. セッションステータスの更新
progress_pct = int((completed / state["total_tasks_count"]) * 100)
running_count = state["total_tasks_count"] - completed
hub.flash_update_status(
    activity="executing",
    step=f"バッチ {state['batch_id']}: {completed}/{state['total_tasks_count']} タスク完了 (実行中: {running_count})",
    batch_id=state["batch_id"],
    progress_pct=progress_pct,
    subagents_running=running_count,
    subagents_completed=completed
)

print(f"タスク {task_id} をステータス '{status}' で記録しました。")
print(f"現在の進捗: {completed}/{state['total_tasks_count']}")
