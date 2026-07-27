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
            "id": "T-batch_ff20df-bug_hunter-000",
            "message": "verify_council_v2.py における古いrequests環境での AttributeError 回避、timeoutアノテーション修正、および CLIからの --timeout None パースサポートを実装。検証テスト4件追加、47テスト PASSを確認。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_ff20df-bug_hunter-001",
            "message": "wave_scheduler.py において wave_size=None の際に不要な UserWarning 警告を出さずフォールバック処理を行うガードを導入。UserWarning をアサートするテストを追加、20テスト PASSを確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_ff20df-bug_hunter-002",
            "message": "flash_assign_subagents_8.py に対するテストコードを新規作成。主要関数への正常系・異常系・例外時の検証を含む 15件の単体テストを実装。15テスト PASSを確認。",
            "files": [
                "tests/test_flash_assign_subagents_8.py"
            ]
        },
        {
            "id": "T-batch_ff20df-bug_hunter-003",
            "message": "run_session_end.py の例外キャッチ修正に伴い、技術負債台帳に残存していた TD-1288 を TDR API で fixed とし解消。検証テストを1件追加、24テスト PASSを確認。",
            "files": [
                "tests/test_run_session_end.py",
                "backend/agents/memory/technical_debt_index.json",
                "backend/TECHNICAL_DEBT_REGISTRY.md"
            ]
        },
        {
            "id": "T-batch_ff20df-bug_hunter-004",
            "message": "_e2e_cycle3.py において urlopen レスポンスおよび接続の確実な close 処理（ResourceWarning 回避）をリファクタリング。close 保証検証などの単体テスト10件を追加、59テスト PASSを確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py",
                "backend/tests/pytest.ini"
            ]
        },
        {
            "id": "T-batch_ff20df-bug_hunter-005",
            "message": "council_graph.py において APIキー未設定時の aclose() での AttributeError クリーンアップ警告を解消するため早期ガード節を追加。検証テストを追加、53テスト PASSを確認。",
            "files": [
                "backend/agents/council_graph.py",
                "backend/tests/test_council_graph.py"
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
