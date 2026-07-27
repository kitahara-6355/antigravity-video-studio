import sys
import os
import json

sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('./backend'))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("851baf17-cfa5-4c9f-b4d2-9647773dc645")
    
    # 完了したタスクのマーク
    completed_tasks = {
        "T-batch_b2b7f6-bug_hunter-001": {
            "message": "Pydantic警告抑制の排除、FastAPI HTTPExceptionの伝播保証（except HTTPExceptionの追加）",
            "changed_files": ["backend/routers/error_schemas.py", "backend/tests/test_error_schemas.py", "pytest.ini"]
        },
        "T-batch_b2b7f6-bug_hunter-002": {
            "message": "音声なし動画のクラッシュ防止、テロップフォントサイズ引数の追加、テスト追加",
            "changed_files": ["backend/theme_telop.py", "backend/combined_overlay.py", "backend/design_alternatives.py", "backend/tests/test_design_alternatives.py"]
        },
        "T-batch_b2b7f6-bug_hunter-003": {
            "message": "重複登録時のIntegrityError是正、例外キャッチ復旧、TDRへの記録、テスト追加",
            "changed_files": ["backend/agents/stage_bound_agent.py", "backend/model_governance.py", "backend/tests/test_stage_bound_agent_extra.py"]
        },
        "T-batch_b2b7f6-bug_hunter-004": {
            "message": "WebSocketクリーンアップ時のasyncio.CancelledErrorの安全な無視処理追加",
            "changed_files": ["backend/websocket_handler.py"]
        },
        "T-batch_b2b7f6-bug_hunter-005": {
            "message": "グローバルなインポートパス汚染の排除、バリデーション・エラー処理等のテスト追加",
            "changed_files": ["backend/routers/approval_router.py", "backend/tests/test_approval_router.py"]
        },
        "T-batch_b2b7f6-bug_hunter-006": {
            "message": "不正正規表現や異常レコード時の安全処理追加、フォールバックのTDR記録、テスト追加",
            "changed_files": ["backend/quality_gate_ai.py", "backend/quality_gate_plugins.py", "backend/agents/workers/quality_gate_worker.py"]
        }
    }
    
    for task_id, report in completed_tasks.items():
        hub.mark_task_done(task_id, "pass", report)
        print(f"Marked task {task_id} as pass.")
        
    # ハングしたタスクを fail としてマーク
    hung_tasks = [
        "T-batch_b2b7f6-bug_hunter-007",
        "T-batch_b2b7f6-bug_hunter-008"
    ]
    for task_id in hung_tasks:
        hub.mark_task_done(task_id, "fail", {
            "error": "SUBAGENT_TIMEOUT: 10分超経過により親エージェントによって強制終了",
            "changed_files": []
        })
        print(f"Marked task {task_id} as fail.")
        
    # 心拍更新
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

if __name__ == '__main__':
    main()
