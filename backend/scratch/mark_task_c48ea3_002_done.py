import sys
import os
import json

# プロジェクトのルートディレクトリおよび backend ディレクトリを動的に解決して sys.path に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def _register_technical_debt(err: Exception) -> None:
    """例外発生時に技術負債登録を試みる"""
    try:
        store = TechnicalDebtStore()
        store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/scratch/mark_task_c48ea3_002_done.py",
            line_number=51,
            pattern="except Exception as e:",
            cause_pattern="DP-01",
            fix_pattern="具体的な例外キャッチへのリファクタリング",
            registered_by="thumbnail_task_27",
            notes=f"スクリプト実行時エラーのキャッチ: {str(err)}",
            tags=["scratch", "error_handling"]
        )
    except (ValueError, OSError) as tdr_err:
        print(f"Failed to register technical debt (Expected): {tdr_err}", file=sys.stderr)
    except RuntimeError as tdr_err:
        print(f"Failed to register technical debt (Unexpected): {tdr_err}", file=sys.stderr)

def main():
    """タスクの完了を OrchestrationHub に報告するメイン関数"""
    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()
        hub.mark_task_done(
            task_id="T-batch_c48ea3-thumbnail-002",
            result="pass",
            report={
                "message": "routers/admin_analytics_router.py: カバレッジ 100% 維持。追加のテストコード変更なし",
                "changed_files": []
            }
        )
    except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        _register_technical_debt(e)
        print(f"Expected processing error executing mark_task_c48ea3_002_done: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        _register_technical_debt(e)
        print(f"Unexpected critical error executing mark_task_c48ea3_002_done: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
