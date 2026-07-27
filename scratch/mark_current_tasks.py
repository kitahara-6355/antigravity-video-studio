import sys
import os
import json

sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 本チャットのセッションIDを登録
    hub.register_flash_conversation_id("e35c44a6-10a1-43c9-8a32-d76439eb554b")
    
    # 1. 心拍更新
    hub.flash_update_heartbeat()
    
    # 2. タスク T-batch_0dba58-test_weaver-001 の完了マーク
    hub.mark_task_done(
        "T-batch_0dba58-test_weaver-001",
        "pass",
        {
            "subagent_id": "cbf67cb5-a67e-446b-a423-dc0f7afb9540",
            "message": "scratch/remove_old_worktrees.py に対するユニットテストの追加とカバレッジ100%達成。",
            "changed_files": []
        }
    )
    print("Marked T-batch_0dba58-test_weaver-001 as pass.")
    
    # 3. タスク T-batch_0dba58-thumbnail-001 の完了マーク
    hub.mark_task_done(
        "T-batch_0dba58-thumbnail-001",
        "pass",
        {
            "subagent_id": "5e99b800-e722-4c44-9dc8-e512e5a80c73",
            "message": "subtitle_preview.py のサムネイル生成・画像処理ロジックの改善。アスペクト比(16:9)補正、高解像度化(1280x720以上)、4MB未満の段階的品質低下リトライ、Pillowによる画像検証、SQLiteロック対応自動マイグレーション等を実装し、テストをPASS。",
            "changed_files": ["backend/subtitle_preview.py"]
        }
    )
    print("Marked T-batch_0dba58-thumbnail-001 as pass.")
    
    # 4. 最新ステータス表示
    status = hub.generate_flash_status()
    print("=== STATUS ===")
    print(status["formatted"])
    print("==============")

if __name__ == "__main__":
    main()
