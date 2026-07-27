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
            "id": "T-batch_c78e2c-bug_hunter-000",
            "message": "wave_scheduler.py における int のサブクラス判定を isinstance 化し、型アノテーションの不整合や警告を解消。追加テストを含む17件のテストPASSを確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_c78e2c-bug_hunter-001",
            "message": "flash_assign_subagents_8.py のテストにおいて、重複割り当て制御および正しいモックパッチ設定を適用。全28件のテストPASSを確認。",
            "files": [
                "backend/agents/orchestration/flash_assign_subagents_8.py",
                "backend/tests/test_flash_assign_subagents_8.py"
            ]
        },
        {
            "id": "T-batch_c78e2c-bug_hunter-002",
            "message": "verify_council_v2.py の _process_response 関数で、raise_for_status() によって非2xx（エラー）時に else 句のログ出力コードへ到達しなかったデッドコードバグを解消。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_c78e2c-bug_hunter-003",
            "message": "_e2e_cycle3.py において、HTTPError 時の socket オブジェクトの明示的クローズにより、ResourceWarning（リソースリーク）を解消。全47件のテストPASSを確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py"
            ]
        },
        {
            "id": "T-batch_c78e2c-bug_hunter-004",
            "message": "run_session_end.py の main() で汎用 Exception キャッチを追加、clean_sys_path における sys.path 参照バグを修正。全22テストPASSを確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_c78e2c-bug_hunter-005",
            "message": "test_council_graph.py の二重CR改行コードの修正、importlib.reload によるグローバル汚染の防止、および faster_whisper プリロードによる PyTorch docstring 二重登録例外の解消。73 Passed を確認。",
            "files": [
                "backend/tests/test_council_graph.py",
                "backend/tests/test_routers_health.py"
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
