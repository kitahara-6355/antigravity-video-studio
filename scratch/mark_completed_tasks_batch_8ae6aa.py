import sys
import os

sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation\backend")
sys.path.insert(0, r"c:\Users\PC_User\Desktop\script\video-automation")

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    conv_id = "ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1"
    hub.register_flash_conversation_id(conv_id)
    
    tasks = [
        {
            "id": "T-batch_8ae6aa-bug_hunter-000",
            "message": "verify_council_v2.py において、timeout 引数に対する bool 型のバリデーションを厳密化。不適切な float キャストによる1.0秒での通過を回避する例外処理を追加。38テスト PASSを確認。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_8ae6aa-bug_hunter-001",
            "message": "wave_scheduler.py において、型アノテーションの拡張および検証を実施。18テスト PASSを確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_8ae6aa-bug_hunter-002",
            "message": "flash_assign_subagents_8.py のテストにおいて、多重ロードされるモジュールのインポート元パッケージ属性をモックターゲットに設定することで runpy 再インポート時のモック抜けバグを解消。29テスト PASSを確認。",
            "files": [
                "backend/tests/test_flash_assign_subagents_8.py"
            ]
        },
        {
            "id": "T-batch_8ae6aa-bug_hunter-003",
            "message": "_e2e_cycle3.py における e.close() ガードによるリソースリーク解消の機能継続検証を実施。コード変更なしで47テスト PASSを確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py"
            ]
        },
        {
            "id": "T-batch_8ae6aa-bug_hunter-004",
            "message": "run_session_end.py において、例外ハンドリングの強化および sys.path 二重インポートによる警告を解消。22テスト PASSを確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_8ae6aa-bug_hunter-005",
            "message": "council_graph.py において、run_council および ThumbnailResolver で発生する想定外の例外時に技術負債台帳 (TDR) へ自動的に負債を登録する仕組みを追加。52テスト PASSを確認。",
            "files": [
                "backend/agents/council_graph.py",
                "backend/tests/test_council_graph.py",
                "backend/tests/test_routers_health.py",
                "backend/agents/memory/technical_debt_index.json",
                "backend/TECHNICAL_DEBT_REGISTRY.md"
            ]
        }
    ]
    
    for t in tasks:
        report = {
            "message": t["message"],
            "changed_files": t["files"]
        }
        print(f"Marking task {t['id']} as pass...")
        hub.mark_task_done(t["id"], "pass", report)
        
    hub.flash_update_heartbeat()
    
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
