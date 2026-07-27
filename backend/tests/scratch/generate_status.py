import sys
import os

# プロジェクトルートを python path に追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from backend.agents.orchestration import OrchestrationHub
from backend.agents.memory.technical_debt import TechnicalDebtStore

def main():
    try:
        hub = OrchestrationHub()
        # 自身の conversation_id を常に登録
        hub.register_flash_conversation_id("2c563fff-a220-4ba2-8e1f-2f05e4b5a090")
        
        if len(sys.argv) > 1 and sys.argv[1] == "heartbeat":
            hub.flash_update_heartbeat()
            print("Heartbeat updated.")
        elif len(sys.argv) > 1 and sys.argv[1] == "end":
            reason = sys.argv[2] if len(sys.argv) > 2 else "ミッション完遂"
            hub.flash_session_end(reason)
            print(f"Session ended: {reason}")
        else:
            status = hub.generate_flash_status()
            print(status.get("formatted", "No formatted status available."))
    except Exception as e:
        print(f"Error in generate_status.py: {e}", file=sys.stderr)
        try:
            import inspect
            frame = inspect.currentframe()
            line_number = frame.f_lineno if frame else 0
            
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="tests/scratch/generate_status.py",
                line_number=line_number,
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="例外の厳密な個別型ハンドリングとバリエーションを適用する",
                registered_by="bug_hunter_task_6",
                notes=f"generate_status.py error: {e}",
                tags=["generate_status", "except_exception"]
            )
        except Exception as register_err:
            print(f"Failed to register technical debt: {register_err}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
