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
    
    # Mark thumbnail-000
    task_id = "T-batch_379828-thumbnail-000"
    report = {
        "message": "comprehensive_preview.py に対し、force_enhance 引数の導入による強制補正ロジックの追加およびアウトライン描画の円形フォールバック処理を実装し、画質・品質検証テストを正常にクリアしました。",
        "changed_files": [
            "backend/comprehensive_preview.py",
            "tests/test_comprehensive_preview.py"
        ]
    }
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("=== Flash Status ===")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
