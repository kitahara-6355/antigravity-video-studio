"""
OrchestrationHub でタスクを完了としてマークするためのスクリプト。
"""
import sys
import os
import argparse

# プロジェクトのルートディレクトリを動的に解決して sys.path に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# フォールバックパスの追加
fallback_path = "C:/Users/PC_User/Desktop/script/video-automation"
if fallback_path not in sys.path:
    sys.path.append(fallback_path)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def main():
    """
    コマンドライン引数を解析し、指定されたタスクを OrchestrationHub で完了としてマークする。
    """
    parser = argparse.ArgumentParser(description="Mark a task as done in OrchestrationHub")
    parser.add_argument("--task-id", "-t", default="T-batch_c48ea3-thumbnail-001", help="Task ID to mark")
    parser.add_argument("--result", "-r", default="pass", help="Result of the task")
    parser.add_argument("--message", "-m", default="interactive_preview.py: カバレッジ 100% 達成。例外ハンドリングやAPIリトライ処理のテストを追加", help="Report message")
    parser.add_argument("--changed-files", "-f", nargs="*", default=["backend/tests/test_shared/test_interactive_preview.py"], help="List of changed files")
    args = parser.parse_args()

    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()
        hub.mark_task_done(
            task_id=args.task_id,
            result=args.result,
            report={
                "message": args.message,
                "changed_files": args.changed_files
            }
        )
    except (ImportError, OSError, ValueError, KeyError) as e:
        # 具体的な例外キャッチへのリファクタリングを行い、エラーを技術負債として記録
        try:
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/scratch/mark_task_c48ea3_001_done.py",
                line_number=38,
                pattern="except (ImportError, OSError, ValueError, KeyError) as e:",
                cause_pattern="DP-01",
                fix_pattern="具体的な例外キャッチへのリファクタリング",
                registered_by="thumbnail_task_27",
                notes=f"スクリプト実行時エラーのキャッチ: {str(e)}",
                tags=["scratch", "error_handling"]
            )
        except (ImportError, OSError, ValueError) as tdr_err:
            print(f"Failed to register technical debt: {tdr_err}", file=sys.stderr)
        
        print(f"Error executing mark_task_c48ea3_001_done: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
