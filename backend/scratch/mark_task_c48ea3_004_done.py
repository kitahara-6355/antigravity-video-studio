import sys
import os

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
    try:
        hub = OrchestrationHub()
        hub.flash_update_heartbeat()
        hub.mark_task_done(
            task_id="T-batch_c48ea3-thumbnail-004",
            result="pass",
            report={
                "message": "verified_facts.py: カバレッジ 100% 達成。プルーニングバグの再現テストやファイルI/Oエラーハンドリングパスのテストを追加",
                "changed_files": ["backend/tests/test_verified_facts.py"]
            }
        )
    except Exception as e:
        # 新規 except Exception 追加のため、技術負債台帳に登録
        try:
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/scratch/mark_task_c48ea3_004_done.py",
                line_number=30,
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="具体的な例外キャッチへのリファクタリング",
                registered_by="thumbnail_task_27",
                notes=f"スクリプト実行時エラーのキャッチ: {str(e)}",
                tags=["scratch", "error_handling"]
            )
        except Exception as tdr_err:
            print(f"Failed to register technical debt: {tdr_err}", file=sys.stderr)
        
        print(f"Error executing mark_task_c48ea3_004_done: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
