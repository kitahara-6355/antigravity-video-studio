import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 本セッションの Conversation ID
    conv_id = "24bf7ae4-2090-41d7-a3e6-3c38ab8af798"
    hub.register_flash_conversation_id(conv_id)
    
    task_id = "T-batch_7daa01-thumbnail-000"
    report = {
        "message": "Midnight Amethyst等のプレミアムカラー追加、GaussianBlurを用いたドロップシャドウぼかしの効率的実装、エラーハンドリング（TDR登録連動）の強化。解像度1280x720・比率16:9・サイズ4MB未満・Pillowロード性を自動検証するテスト等を追加し、68テストPASSを確認。",
        "changed_files": [
            "backend/thumbnail_engine/generator.py",
            "tests/test_thumbnail_generator.py"
        ]
    }
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)

    # 心拍更新 (Step 0)
    print("Updating heartbeat...")
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
