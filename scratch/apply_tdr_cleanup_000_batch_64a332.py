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
    
    task_id = "T-batch_64a332-tdr_cleanup-000"
    report = {
        "message": "video_editor_engine.pyのrun_command内の広域例外except Exceptionを、具体的な例外（OSError, ValueError）に限定化。例外伝播とフォールバックを検証する新規テストを追加し、フィットネス関数テスト125件のPASSを確認。",
        "changed_files": [
            "backend/video_editor_engine.py",
            "backend/tests/test_video_editor_run_command.py",
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
