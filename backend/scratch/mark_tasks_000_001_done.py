import sys
from pathlib import Path

# プロジェクトルートの動的解決とsys.pathへの追加
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

def main():
    try:
        from backend.agents.orchestration import OrchestrationHub
    except ImportError as e:
        print(f"エラー: OrchestrationHubのインポートに失敗しました: {e}", file=sys.stderr)
        return 1

    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()

        hub.mark_task_done(
            task_id="T-batch_c48ea3-thumbnail-000",
            result="pass",
            report={
                "message": "clean_rebuild.py: インポートミスを修正し、欠落ファイル検出ルート等のテストを追加、カバレッジ 100% 達成",
                "changed_files": ["backend/clean_rebuild.py", "backend/tests/test_clean_rebuild.py"]
            }
        )

        hub.mark_task_done(
            task_id="T-batch_c48ea3-thumbnail-001",
            result="pass",
            report={
                "message": "interactive_preview.py: カバレッジ 100% 達成。例外ハンドリングやAPIリトライ処理のテストを追加",
                "changed_files": ["backend/tests/test_shared/test_interactive_preview.py"]
            }
        )
        print("タスク T-batch_c48ea3-thumbnail-000 および 001 を完了として正常にマークしました。")
        return 0
    except Exception as e:
        # 新規 except Exception 追加のため、技術負債台帳に登録
        try:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/scratch/mark_tasks_000_001_done.py",
                line_number=39,
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="具体的な例外キャッチへのリファクタリング",
                registered_by="bug_hunter_task_7",
                notes=f"スクリプト実行時エラーのキャッチ: {str(e)}",
                tags=["scratch", "error_handling"]
            )
        except Exception as tdr_err:
            print(f"Failed to register technical debt: {tdr_err}", file=sys.stderr)

        print(f"エラー: タスクのマーク処理中にエラーが発生しました: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
