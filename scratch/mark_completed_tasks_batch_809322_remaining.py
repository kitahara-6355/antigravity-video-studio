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
    
    # 1. Mark thumbnail-001
    task_id_thumb = "T-batch_809322-thumbnail-001"
    report_thumb = {
        "message": "comprehensive_preview.py に対し、巨大画像ハンドリング(MAX_IMAGE_PIXELS)のロバスト化、フォントフォールバックのマルチプラットフォーム強化、およびテスト不具合の補正を行い、画質・品質検証テストを正常にクリアしました。",
        "changed_files": [
            "backend/comprehensive_preview.py",
            "backend/tests/test_comprehensive_preview_thumbnail.py"
        ]
    }
    print(f"Marking task {task_id_thumb} as pass...")
    hub.mark_task_done(task_id_thumb, "pass", report_thumb)

    # 2. Mark test_weaver-000
    task_id_weaver0 = "T-batch_809322-test_weaver-000"
    report_weaver0 = {
        "message": "disk_manager.py において、全機能に対するカバレッジ100%を保証するテストを追加し、テスト全PASSを確認しました。",
        "changed_files": [
            "tests/test_disk_manager.py"
        ]
    }
    print(f"Marking task {task_id_weaver0} as pass...")
    hub.mark_task_done(task_id_weaver0, "pass", report_weaver0)

    # 3. Mark test_weaver-001
    task_id_weaver1 = "T-batch_809322-test_weaver-001"
    report_weaver1 = {
        "message": "ai_rhythm.py において、ロバストネス向上のために5つのテストケース（計35ケース）を追加し、カバレッジ100%維持およびテストPASSを確認しました。",
        "changed_files": [
            "tests/test_shared/test_ai_rhythm.py"
        ]
    }
    print(f"Marking task {task_id_weaver1} as pass...")
    hub.mark_task_done(task_id_weaver1, "pass", report_weaver1)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
