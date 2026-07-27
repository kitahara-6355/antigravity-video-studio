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
    
    task_id = "T-batch_3f0e54-tdr_cleanup-000"
    report = {
        "message": "verified_preview_generator.py内のensure_preview_image_qualityと親ディレクトリ作成時のexcept Exceptionを、具体的例外（TypeError, ValueError, AttributeErrorおよびOSError）に限定化。TechnicalDebtStoreによる解消登録およびユニットテスト28件PASSを確認。",
        "changed_files": [
            "backend/verified_preview_generator.py",
            "backend/agents/memory/technical_debt_index.json",
            "backend/TECHNICAL_DEBT_REGISTRY.md"
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
