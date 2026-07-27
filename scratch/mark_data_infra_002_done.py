import sys
import os

repo_path = r"c:\Users\PC_User\Desktop\script\video-automation"
sys.path.append(repo_path)
sys.path.append(os.path.join(repo_path, "backend"))

from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()
hub.mark_task_done("T-batch_27b234-data_infra-002", "pass", {
    "message": "pipeline_router.py の例外ガードの追加と、テスト追加によるカバレッジ向上（54% -> 55%）、TDRの解決を確認しました。",
    "changed_files": [
        "backend/routers/pipeline_router.py",
        "backend/tests/test_shared/test_cov_pipeline_router.py"
    ]
})
print("Marked data_infra-002 as pass")
