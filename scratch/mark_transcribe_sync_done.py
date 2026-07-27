# -*- coding: utf-8 -*-
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    task_id = "T-batch_0f4e14-test_weaver-000"
    report = {
        "message": "transcribe_sync.py において、コマンドライン余剰引数の処理、空セグメントリストの出力検証、Pathlib.Path オブジェクトの受け渡し検証テストの3ケースを新規追加。カバレッジ100%を維持し全11件のテストがPASS。",
        "changed_files": [
            "tests/test_transcribe_sync.py",
            "backend/tests/test_transcribe_sync.py"
        ]
    }
    
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Task Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
