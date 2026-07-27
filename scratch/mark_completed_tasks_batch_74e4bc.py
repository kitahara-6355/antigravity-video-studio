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
            "id": "T-batch_3a9d37-bug_hunter-000",
            "message": "wave_scheduler.py におけるエラーハンドリングの強化、および collections.abc.Iterable/Mapping への対応による型拡張。テストを4件追加し、計13テストすべてPASSを確認。",
            "files": [
                "backend/agents/orchestration/wave_scheduler.py",
                "backend/tests/test_wave_scheduler.py"
            ]
        },
        {
            "id": "T-batch_3a9d37-bug_hunter-002",
            "message": "flash_assign_subagents_8.py の main() における Broad Exception キャッチ (TD-1287) を廃止。想定される例外を個別にハンドリングし、想定外例外を伝播させるよう改善。テストを追加・修正し全27テストPASSおよびカバレッジ100%を確認。",
            "files": [
                "backend/agents/orchestration/flash_assign_subagents_8.py",
                "backend/tests/test_flash_assign_subagents_8.py"
            ]
        },
        {
            "id": "T-batch_3a9d37-bug_hunter-003",
            "message": "run_session_end.py のインポート位置およびパス解決バグの修正。冗長な Broad Exception を排しエラーハンドリングを強化。テストをPASS確認。",
            "files": [
                "backend/agents/orchestration/run_session_end.py",
                "tests/test_run_session_end.py"
            ]
        },
        {
            "id": "T-batch_3a9d37-bug_hunter-004",
            "message": "_e2e_cycle3.py における例外処理の堅牢化。テストをPASS確認。",
            "files": [
                "backend/tests/_e2e_cycle3.py",
                "backend/tests/test_e2e_cycle3.py"
            ]
        },
        {
            "id": "T-batch_3a9d37-bug_hunter-005",
            "message": "council_graph.py 内の不要な Broad Exception キャッチを削除し例外が正しく伝播するよう修正。テストを2件追加し、計49テストすべてPASSを確認。",
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
