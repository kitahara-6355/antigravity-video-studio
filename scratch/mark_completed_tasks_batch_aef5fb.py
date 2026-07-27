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
            "id": "T-batch_aef5fb-bug_hunter-000",
            "message": "verify_council_v2.py における requests.Session コンテキストマネージャ化、文字数判定の不整合修正、および JSONボディ送信 POSTのサポート実装。検証テスト5件追加、43テスト PASSを確認。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_aef5fb-bug_hunter-001",
            "message": "wave_scheduler.py において、不正値入力およびフォールバック発生時の UserWarning 送出処理、および integer等価な floatキャスト時の余計な警告抑止を実装。検証テスト1件追加、19テスト PASSを確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_aef5fb-bug_hunter-002",
            "message": "flash_assign_subagents_8.py のかつての例外キャッチの修正に伴い、技術負債台帳に残存していた TD-1287 を TDR API で fixed とし不整合を解消。インテグレーションテスト1件追加、30テスト PASSを確認。",
            "files": [
                "backend/tests/test_flash_assign_subagents_8.py",
                "backend/agents/memory/technical_debt_index.json",
                "backend/TECHNICAL_DEBT_REGISTRY.md"
            ]
        },
        {
            "id": "T-batch_aef5fb-bug_hunter-003",
            "message": "run_session_end.py において、flash_session.json 内の conversation_id から親セッションIDをフォールバック取得するようロジックを修正。sys.modules 衝突警告回避テストを追加、23テスト PASSを確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_aef5fb-bug_hunter-004",
            "message": "_e2e_cycle3.py における HTTPError 発生時の接続リソース close処理を追加。実スリープ遅延の排除、fixtureループスコープ警告回避、および検証テスト2件を追加。49テスト PASSを確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py",
                "backend/tests/pytest.ini"
            ]
        },
        {
            "id": "T-batch_aef5fb-bug_hunter-005-split0",
            "message": "council_graph.py の大規模変更対策ステップ1/3（設計・スタブ化）として、TypedDictによる型定義の導入、ThumbnailResolver インターフェースのスタブ化を完了。52テスト PASSを確認。",
            "files": [
                "backend/agents/council_graph.py"
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
