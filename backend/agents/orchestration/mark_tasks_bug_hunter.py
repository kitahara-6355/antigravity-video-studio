import sys
sys.path.insert(0, '.')
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    """mark_tasks_bug_hunter.py のメインエントリーポイント。
    OrchestrationHubを使用して特定のbug_hunterタスクを完了マークします。
    """
    try:
        hub = OrchestrationHub()
        hub.register_flash_conversation_id("a9736a64-a242-485f-942e-bf8476d21fa6")
        
        # 心拍更新
        hub.flash_update_heartbeat()
        
        # bug_hunter-000 完了マーク
        hub.mark_task_done("T-batch_a1eb03-bug_hunter-000", "pass", {
            "message": "settings_manager.py の例外処理改善（ベア except からの TDR 登録連携）。",
            "changed_files": [
                "backend/settings_manager.py",
                "backend/tests/test_settings_manager.py",
                "backend/agents/memory/technical_debt_index.json"
            ]
        })
        
        print("TASK_MARKED_DONE")

        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        sys.stderr.write(f"Error occurred in mark_tasks_bug_hunter main: {e}\n")
        try:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/agents/orchestration/mark_tasks_bug_hunter.py",
                line_number=28,
                pattern="except Exception as e",
                cause_pattern="DP-01",
                fix_pattern="OrchestrationHub呼び出しエラー時のハンドリング",
                registered_by="subagent-bug-hunter",
                notes=f"OrchestrationHub execution failed: {e}",
                tags=["bug_hunter", "except_exception"]
            )
        except (ImportError, OSError, json.JSONDecodeError, ValueError, KeyError) as register_err:
            sys.stderr.write(f"Failed to register technical debt: {register_err}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
