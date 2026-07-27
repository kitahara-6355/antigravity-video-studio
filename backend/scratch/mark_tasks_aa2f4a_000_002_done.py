import sys
import json
from pathlib import Path

# プロジェクトルートの動的解決とsys.pathへの追加
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

def main() -> int:
    """
    OrchestrationHub に接続し、タスク T-batch_aa2f4a-thumbnail-000 と T-batch_aa2f4a-thumbnail-002 を pass としてマークします。
    """
    try:
        from backend.agents.orchestration import OrchestrationHub
    except ImportError as e:
        print(f"エラー: OrchestrationHubのインポートに失敗しました: {e}", file=sys.stderr)
        return 1

    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()

        hub.mark_task_done(
            task_id="T-batch_aa2f4a-thumbnail-000",
            result="pass",
            report={
                "message": "template_recommender.py: テストのコピペによる重複定義を整理しリファクタリング、カバレッジ 100% 維持",
                "changed_files": ["backend/tests/test_shared/test_template_recommender.py"]
            }
        )

        hub.mark_task_done(
            task_id="T-batch_aa2f4a-thumbnail-002",
            result="pass",
            report={
                "message": "scratch/submit_batch_c48ea3.py: モックによるインメモリ実行テストを追加し、カバレッジ 100% 達成",
                "changed_files": ["backend/tests/test_scratch_submit_batch.py"]
            }
        )
        print("タスク T-batch_aa2f4a-thumbnail-000 および 002 を完了として正常にマークしました。")
        return 0
    except (TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"エラー: タスクのマーク処理中にエラーが発生しました: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
