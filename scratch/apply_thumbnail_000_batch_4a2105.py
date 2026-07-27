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
    
    task_id = "T-batch_4a2105-thumbnail-000"
    report = {
        "message": "preview_worker.py内のgenerate_thumbnailロジックを刷新し、Glassmorphism風半透明バナーやビネット等のプレミアムビジュアルを実装。解像度1280x720・比率16:9・サイズ4MB未満・Pillowロード性を自動検証するテスト等を追加し、29テストPASSを確認。",
        "changed_files": [
            "backend/agents/workers/preview_worker.py",
            "tests/test_preview_worker.py"
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
