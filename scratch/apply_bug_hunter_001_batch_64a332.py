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
    
    task_id = "T-batch_64a332-bug_hunter-001"
    report = {
        "message": "quality_gate_agent.pyのcommon_errorsタイポ修正（ずつ/づつ）、各チェック関数での入力型バリデーションおよびNone安全デフォルト値処理、字幕チェック時の例外安全化。対応するテスト追加・修正、フィットネス関数テスト等のPASSを確認。",
        "changed_files": [
            "backend/quality_gate_agent.py",
            "backend/tests/test_quality_gate_agent.py",
            "tests/test_quality_gate_agent.py"
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
