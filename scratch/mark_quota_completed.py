# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(r"C:\Users\PC_User\Desktop\script\video-automation\backend")))
sys.path.insert(0, str(Path(r"C:\Users\PC_User\Desktop\script\video-automation")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()

    # T-batch_d6d052-test_weaver-007 (admin_quota_router) を完了マーク
    hub.mark_task_done(
        "T-batch_d6d052-test_weaver-007",
        "pass",
        {
            "message": "backend/routers/admin_quota_router.py に対するユニットテストを新規追加し、カバレッジを 86% から 100% に向上させました。",
            "changed_files": ["backend/tests/test_shared/test_admin_quota_coverage.py"]
        }
    )
    print("Marked admin_quota_router task done.")

if __name__ == "__main__":
    main()
