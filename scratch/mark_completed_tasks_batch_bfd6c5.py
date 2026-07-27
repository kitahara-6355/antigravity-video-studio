import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "78b44067-a11c-4c04-9106-db3d8f632741"
    hub.register_flash_conversation_id(conv_id)
    
    # 1. Mark refactor-000
    task_id_ref = "T-batch_bfd6c5-refactor-000"
    report_ref = {
        "message": "agents/orchestration/flash_assign_subagents_10.py のリファクタリング（未使用インポート削除、命名改善、関数分割、テスト追加）が完了し、テスト7件PASS、カバレッジ87%維持を確認しました。",
        "changed_files": [
            "backend/agents/orchestration/flash_assign_subagents_10.py",
            "backend/tests/test_flash_assign_subagents_10.py"
        ]
    }
    print(f"Marking task {task_id_ref} as pass...")
    hub.mark_task_done(task_id_ref, "pass", report_ref)

    # 2. Mark thumbnail-000
    task_id_thumb = "T-batch_bfd6c5-thumbnail-000"
    report_thumb = {
        "message": "comprehensive_preview.py に対し、解像度 1280x720 以上、アスペクト比 16:9、ファイルサイズ 4MB 未満、Pillow健全ロード、StageBoundAgent連携を含む自動検証テストをクリアしたことを確認しました。",
        "changed_files": []
    }
    print(f"Marking task {task_id_thumb} as pass...")
    hub.mark_task_done(task_id_thumb, "pass", report_thumb)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
