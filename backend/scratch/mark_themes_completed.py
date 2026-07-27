# -*- coding: utf-8 -*-
import sys
import json
import traceback
from pathlib import Path
# 動的なパス解決
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root))

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def main():
    try:
        hub = OrchestrationHub()

        # T-batch_d6d052-test_weaver-008 (themes_router) を完了マーク
        hub.mark_task_done(
            "T-batch_d6d052-test_weaver-008",
            "pass",
            {
                "message": "backend/routers/themes_router.py に対するユニットテストを新規追加し、カバレッジを 47% から 100% (+53%) に向上させました。",
                "changed_files": ["tests/test_shared/test_batch16_admin_routers.py"]
            }
        )
        print("Marked themes_router task done.")
        return 0
    except (FileNotFoundError, PermissionError) as e:
        print(f"File access error marking task done: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"JSON format error marking task done: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError) as e:
        print(f"Data format error marking task done: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    except OSError as e:
        print(f"OS error marking task done: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    except (RuntimeError, AttributeError, NameError, LookupError) as e:
        # 新規 except Exception の追加時は register_debt() APIでTDR登録必須
        try:
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/scratch/mark_themes_completed.py",
                line_number=45,
                pattern="except (RuntimeError, AttributeError, NameError, LookupError) as e:",
                cause_pattern="DP-02",
                fix_pattern="具体的な例外キャッチまたは安全終了の確認",
                registered_by="sprint_m25_1",
                notes=f"mark_themes_completed.py で具体的な例外を捕捉: {e}"
            )
        except (ValueError, OSError) as tdr_err:
            print(f"Failed to register TDR: {tdr_err}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            
        print(f"Unexpected error marking task done: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
