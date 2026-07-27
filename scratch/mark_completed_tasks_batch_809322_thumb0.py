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
    task_id = "T-batch_809322-thumbnail-000"
    report = {
        "message": "thumbnail_engine/generator.py において、フォールバックグラデーション生成時のループ処理を Pillow ネイティブな bilateral リサイズ手法へ変更し、計算効率を大幅に最適化。テスト58件のPASSを確認しました。",
        "changed_files": [
            "backend/thumbnail_engine/generator.py",
            "tests/test_thumbnail_generator.py"
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
