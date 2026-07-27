import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

state_path = project_root / "scratch/flash_runner_state.json"
if not state_path.exists():
    print("エラー: 状態ファイルが見つかりません。")
    sys.exit(1)

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

batch_id = state["batch_id"]
tasks = state["tasks"]

passed = sum(1 for t in tasks.values() if t["result"] == "pass")
failed = sum(1 for t in tasks.values() if t["result"] == "fail")
total = len(tasks)

print(f"=== バッチ報告の準備 ===")
print(f"バッチID: {batch_id}")
print(f"結果: passed={passed}, failed={failed}, total={total}")

if passed + failed < total:
    print("エラー: 未完了のタスクがあります。報告を中止します。")
    sys.exit(1)

# OrchestrationHub へ報告
hub = OrchestrationHub()

# 報告の提出
print("OrchestrationHub へバッチ報告を送信中...")
hub.submit_batch_report(batch_id, {
    "passed": passed,
    "failed": failed,
    "total": total
})

# 生存確認を送信
hub.flash_heartbeat()
print("生存確認 (Heartbeat) を送信しました。")

# 現在のフェーズ状態確認
phase_state = hub.get_phase_state()
print(f"\n=== フェーズ状態 ===")
print(f"現在Phase: {phase_state.get('current_phase')}, Milestone: {phase_state.get('current_milestone')}")
print(f"Awaiting Opus: {phase_state.get('awaiting_opus')}")

# 次のバッチの取得を試みる
print("\n次のバッチ取得を試みています...")
next_batch = hub.get_next_batch(
    phase=phase_state.get("current_phase"),
    milestone=phase_state.get("current_milestone"),
    batch_size=6
)

if next_batch:
    print(f"次のバッチを取得しました！ タスク件数: {len(next_batch)}")
    print(next_batch)
    
    # 状態ファイルを次のバッチ用に初期化
    queue_status = hub.get_queue_status()
    new_batch_id = queue_status["batch_id"]
    
    # 新しいタスク状態を再構築
    new_tasks = {}
    for task in next_batch:
        new_tasks[task["id"]] = {
            "task_id": task["id"],
            "group": task["group"],
            "target_module": task["target_module"],
            "instruction": task.get("instruction", ""),
            "status": "pending",
            "subagent_id": None,
            "result": None,
            "report": None
        }
        
    new_state = {
        "batch_id": new_batch_id,
        "phase": queue_status["phase"],
        "milestone": queue_status["milestone"],
        "tasks": new_tasks,
        "completed_tasks_count": 0,
        "total_tasks_count": len(new_tasks)
    }
    
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=2, ensure_ascii=False)
        
    print(f"状態ファイルを初期化しました（次のバッチ用）: {new_batch_id}")
else:
    print("次のバッチはありません。タスクキューが空か、あるいはフェーズの完了ゲートによりOpusレビュー待ちです。")
    # 状態ファイルのバッチIDをクリア
    state["batch_id"] = None
    state["tasks"] = {}
    state["completed_tasks_count"] = 0
    state["total_tasks_count"] = 0
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
