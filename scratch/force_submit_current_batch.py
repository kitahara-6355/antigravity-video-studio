import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))
sys.path.append(str(project_root / "backend"))

from backend.agents.orchestration import OrchestrationHub

# task_queue.json のパス
queue_path = project_root / "backend/agents/orchestration/task_queue.json"

if not queue_path.exists():
    print("エラー: task_queue.json が存在しません。")
    sys.exit(1)

with open(queue_path, "r", encoding="utf-8") as f:
    queue = json.load(f)

batch_id = queue.get("current_batch_id")
if not batch_id:
    print("エラー: current_batch_id が設定されていません。")
    sys.exit(1)

tasks = queue.get("tasks", [])
passed = sum(1 for t in tasks if t.get("status") == "pass")
failed = sum(1 for t in tasks if t.get("status") == "fail")
total = len(tasks)

print(f"=== 手動バッチ強制完了 ===")
print(f"バッチID: {batch_id}")
print(f"ステータス: passed={passed}, failed={failed}, total={total}")

# 各タスクのチェック
if passed + failed < total:
    print("エラー: まだ未完了のタスクが残っています。")
    sys.exit(1)

hub = OrchestrationHub()

# バッチレポートの送信 (マージと自動コミットを実行)
print("OrchestrationHub へバッチ完了を報告中...")
hub.submit_batch_report(batch_id, {
    "passed": passed,
    "failed": failed,
    "total": total
})

# 生存確認を送信
hub.flash_heartbeat()
print("Heartbeatを送信しました。")

# 次のバッチを起票させる
phase_state = hub.get_phase_state()
phase = phase_state.get("current_phase")
milestone = phase_state.get("current_milestone")
print(f"次のバッチを起票中... Phase {phase} / {milestone}")

next_batch = hub.get_next_batch(
    phase=phase,
    milestone=milestone,
    batch_size=6
)

if next_batch:
    print(f"次のバッチを正常に起票しました！ ID: {hub.get_queue_status().get('batch_id')}, 件数: {len(next_batch)}")
else:
    print("次のバッチはありません。タスクキューが空か、あるいはゲート監査またはOpusレビュー待ちです。")

# Flashシステムステータス表示義務 (generate_flash_status)
print("-------------------- STATUS --------------------")
status = hub.generate_flash_status()
print(status["formatted"])
print("------------------------------------------------")

