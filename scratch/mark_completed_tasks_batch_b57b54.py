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
            "id": "T-batch_b57b54-bug_hunter-000",
            "message": "200以外の成功コード（201, 204等）への対応、および204時の空レスポンスガードロジックの追加。timeout引数の型をfloatに変換して検証する堅牢性の向上。新規4テストを含む個別36テスト、全体880テストのPASSとカバレッジ100%を確認。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_b57b54-bug_hunter-001",
            "message": "すでに同じエージェントIDが割り当てられている場合はtask_queue.jsonへの不要な書き込みを防止するようロジックを修正。また、テストコード内の誤ったモックパッチターゲットの修正と、干渉防止のためのテストデータフレッシュ化の適用。",
            "files": [
                "backend/agents/orchestration/flash_assign_subagents_8.py",
                "backend/tests/test_flash_assign_subagents_8.py",
                "pytest.ini"
            ]
        },
        {
            "id": "T-batch_b57b54-bug_hunter-002",
            "message": "PYTHONPATHがないテスト実行環境下でモジュール収集エラー（FAIL）が発生する問題を、インポート文のインポートパス修正（agents.orchestrationへ変更）により解消。警告抑止を検証するテストを追加。全16テストPASSを確認。",
            "files": [
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_b57b54-bug_hunter-003",
            "message": "main()の広域例外キャッチを具体的な例外クラス（RuntimeError等）に狭め技術負債 TD-1288 を解消。レポート生成時の日付ズレリスクをtimestamp引数の共通引き回しにより完全解決。全21テストのPASSとWarningゼロを確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_b57b54-bug_hunter-004",
            "message": "urllib.request.urlopen で HTTPError 発生時にソケット接続がクローズされないリソースリーク（ResourceWarning）を解消するため、e.close() を確実に呼ぶ例外・フォールバックガード処理を実装。新規4テストを含む全47テストのPASSを確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py"
            ]
        },
        {
            "id": "T-batch_b57b54-bug_hunter-005",
            "message": "ThumbnailResolver.__new__ 内の例外捕捉ブロックにおいて、予期しない一般例外 Exception 以外のサブクラス（ZeroDivisionErrorなど）が RuntimeError に誤ってラップされずにそのまま透過的に送出されるように修正、および検証完了。",
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
        
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # ステータス確認
    status = hub.generate_flash_status()
    print("--- Flash Status After Tasks Done ---")
    print(status.get("formatted", ""))

if __name__ == "__main__":
    main()
