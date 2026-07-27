import os
import sys

# 動的にパスを解決して sys.path に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
backend_dir = os.path.join(project_root, "backend")

if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # thumbnail-000 完了マーク
    hub.mark_task_done("T-batch_214e16-thumbnail-000", "pass", {
        "message": "verify_thumbnail_gen.py のサムネイル処理改善と品質検証・テスト追加。",
        "changed_files": [
            "backend/verify_thumbnail_gen.py",
            "backend/tests/test_verify_thumbnail_gen.py"
        ]
    })
    
    # バッチ完了報告
    hub.submit_batch_report("batch_214e16", {
        "passed": 6,
        "failed": 0,
        "skipped": 0,
        "total": 6,
    })
    print("BATCH_SUBMITTED")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
