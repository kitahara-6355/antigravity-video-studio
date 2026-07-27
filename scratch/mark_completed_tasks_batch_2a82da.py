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
            "id": "T-batch_2a82da-bug_hunter-000",
            "message": "tests/test_flash_assign_subagents_8.py 内の多数の構文エラーやアサーションのバグを修正。例外ハンドリングの網羅的検証テストを追加し、テストカバレッジ 99%（全49テスト PASS）を確認。プロダクションコードへの変更はなし。",
            "files": [
                "backend/tests/test_flash_assign_subagents_8.py"
            ]
        },
        {
            "id": "T-batch_2a82da-bug_hunter-001",
            "message": "isinstance(size, int) では bool 型を拒否できない論理バグを type(size) is not int に修正して厳格化。非整数の負の文字列へのフォールバック処理テストを追加。カバレッジ 100% と全843件の回帰テスト PASS を確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_2a82da-bug_hunter-002",
            "message": "timeout=None での型エラーを if timeout is not None validation 条件の追加で解消。また、HTTPError ハンドラのデッドコード化を response.raise_for_status() の追加により適正化。全32テスト PASS、カバレッジ 100% を確認。",
            "files": [
                "backend/verify_council_v2.py",
                "backend/tests/test_verify_council_v2.py"
            ]
        },
        {
            "id": "T-batch_2a82da-bug_hunter-003",
            "message": "スクリプト直接実行時の sys.path 重複ガード条件の導入。テスト時の OrchestrationHub モックのインポート不具合の解消、および sys.path の退避・復元 context manager の導入によりテスト環境の汚染を防止。全842テスト PASS を確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_2a82da-bug_hunter-004",
            "message": "APIレスポンスの stages キーが None や非リスト型である場合に発生する TypeError によるクラッシュを回避するため、空リストへの安全なフォールバックガード処理を実装。全43テスト PASS、カバレッジ 100% を確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py"
            ]
        },
        {
            "id": "T-batch_2a82da-bug_hunter-005",
            "message": "ThumbnailResolver.__new__ 内の例外捕捉ブロックにおいて、予期しない一般例外 Exception が RuntimeError にラップされずにそのまま送出されていたバグを修正。一般例外のラップテストを追加し、全34テストの PASS を確認。",
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
