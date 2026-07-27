import sys
import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = r"C:\Users\PC_User\Desktop\script\video-automation"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.flash_update_heartbeat()
    print("Heartbeat updated.")

    agents_config = [
        {
            "id": "T-batch_1ec60a-bug_hunter-000",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-0--flash-assign-subagents-8--self-d059b2cb",
            "files": [("backend/tests/test_flash_assign_subagents_8.py", "backend/tests/test_flash_assign_subagents_8.py")],
            "test": "backend/tests/test_flash_assign_subagents_8.py",
            "msg": "test_flash_assign_subagents_8.py において tmp_path の代わりにマウントされた scratch ディレクトリを使用するように修正し、テスト test_assign_subagents_scratch_cleanup を追加して 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_1ec60a-bug_hunter-001",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-1--error-reporter--self-f111e5a5",
            "files": [
                ("backend/error_reporter.py", "backend/error_reporter.py"),
                ("backend/tests/test_backend_error_reporter.py", "backend/tests/test_backend_error_reporter.py")
            ],
            "test": "backend/tests/test_backend_error_reporter.py",
            "msg": "error_reporter.py における型検証、重複FAQ登録ValueError、RLockスレッド同期の堅牢化を行い、テスト test_error_report_manager_atomic_save_tmp_file_pattern_without_uuid 等を追加して 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_1ec60a-bug_hunter-002",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-2--learning-integration--self-273d246a",
            "files": [
                ("backend/agents/orchestration/learning_integration.py", "backend/agents/orchestration/learning_integration.py"),
                ("backend/tests/test_learning_integration.py", "backend/tests/test_learning_integration.py")
            ],
            "test": "backend/tests/test_learning_integration.py",
            "msg": "learning_integration.py での引数が None の場合のグローバルパスフォールバックを追加し、テスト test_hub_refresh_and_cache_respects_global_paths を追加して 100% PASS を確認しました。"
        },
        {
            "id": "T-batch_1ec60a-bug_hunter-003",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-3--wave-scheduler--self-2b0e3167",
            "files": [
                ("implementation_plan.md", "implementation_plan.md"),
                ("backend/tests/test_wave_scheduler.py", "backend/tests/test_wave_scheduler.py")
            ],
            "test": "backend/tests/test_wave_scheduler.py",
            "msg": "wave_scheduler の要件 REQ-WAVE-01 を implementation_plan.md に明記し、テストアノテーションを紐付けることで、設計乖離ガード FF-30 の合格を確認しました。"
        },
        {
            "id": "T-batch_1ec60a-bug_hunter-004",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-4--council-graph--self-90ac6a88",
            "files": [
                ("backend/agents/council_graph.py", "backend/agents/council_graph.py"),
                ("backend/tests/test_council_graph.py", "backend/tests/test_council_graph.py")
            ],
            "test": "backend/tests/test_council_graph.py",
            "msg": "council_graph.py の ThumbnailResolver でのモック回避ロジック is_mock_val を削除し、以前の仕様に戻すことで、テスト test_thumbnail_resolver_mock_binding_propagation の合格を確認しました。"
        },
        {
            "id": "T-batch_1ec60a-bug_hunter-005",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\4d5b3bac-aa1d-4822-979c-bd4e443dcb95\.system_generated\worktrees\subagent-bug-hunter-Agent-5--mark-tasks-p27-batch-449dfb--self-5903762a",
            "files": [
                ("backend/agents/orchestration/mark_tasks_p27_batch_449dfb.py", "backend/agents/orchestration/mark_tasks_p27_batch_449dfb.py"),
                ("tests/test_mark_tasks_p27_batch_449dfb.py", "tests/test_mark_tasks_p27_batch_449dfb.py")
            ],
            "test": "tests/test_mark_tasks_p27_batch_449dfb.py",
            "msg": "mark_tasks_p27_batch_449dfb.py でのインポートパス解決、進捗表示、一括レポート送信の機能強化を行い、テスト test_mark_tasks_p27_batch_449dfb.py を追加して 100% PASS を確認しました。"
        }
    ]

    for config in agents_config:
        task_id = config["id"]
        wt_path = config["wt"]
        print(f"\n=== Syncing {task_id} ===")
        
        # コピー実行
        for src_rel, dest_rel in config["files"]:
            src_path = os.path.join(wt_path, src_rel)
            if not os.path.exists(src_path):
                src_path = os.path.join(wt_path, src_rel.replace("backend/", ""))
                
            dest_path = os.path.join(PROJECT_ROOT, dest_rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {src_path} -> {dest_path}")

        # テスト実行
        test_file = config["test"]
        print(f"Running pytest for {test_file}...")
        
        # PYTHONPATHにPROJECT_ROOTとPROJECT_ROOT/backendを明示的に指定してpytestを実行
        env = os.environ.copy()
        python_path = f"{PROJECT_ROOT};{os.path.join(PROJECT_ROOT, 'backend')}"
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = f"{python_path};{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = python_path
            
        res = subprocess.run(["pytest", test_file, "--timeout=300"], capture_output=True, text=True, env=env)
        if res.returncode == 0:
            print("Test passed.")
            report = {
                "message": config["msg"],
                "changed_files": [os.path.join(PROJECT_ROOT, f[1]) for f in config["files"]]
            }
            hub.mark_task_done(task_id, "pass", report)
            print(f"Marked task {task_id} as pass.")
        else:
            print(f"Test failed on main project. Output:")
            print(res.stdout)
            print(res.stderr)

if __name__ == "__main__":
    main()
