import sys
import os
import shutil
import subprocess

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
            "id": "T-batch_7d265f-bug_hunter-001",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-7d265f-bug-hunter-001-self-ea5313d4",
            "files": [
                ("backend/agents/orchestration/health_check.py", "backend/agents/orchestration/health_check.py"),
                ("backend/agents/orchestration/hub_status.py", "backend/agents/orchestration/hub_status.py"),
                ("backend/tests/test_health_check.py", "backend/tests/test_health_check.py")
            ],
            "tests": ["backend/tests/test_health_check.py"],
            "msg": "health_check.py および hub_status.py において ETA 情報をキャッシュ化して 2重計算による drift ねじれを解消し、flash_reports パース堅牢化を追加しました。さらに test_health_check.py 内の mock_paths を一括 monkeypatch パス定数置換する形に拡張し、パス定数型 TypeError や本番ファイル汚染問題を完全解消して全39件を PASS させました。"
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
        all_passed = True
        env = os.environ.copy()
        python_path = f"{PROJECT_ROOT};{os.path.join(PROJECT_ROOT, 'backend')}"
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = f"{python_path};{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = python_path

        for test_file in config["tests"]:
            print(f"Running pytest for {test_file}...")
            res = subprocess.run(["pytest", test_file, "--timeout=300"], capture_output=True, text=True, env=env)
            if res.returncode == 0:
                print(f"Test {test_file} passed.")
            else:
                print(f"Test {test_file} failed. Output:")
                print(res.stdout)
                print(res.stderr)
                all_passed = False
                break

        if all_passed:
            report = {
                "message": config["msg"],
                "changed_files": [os.path.join(PROJECT_ROOT, f[1]) for f in config["files"]]
            }
            hub.mark_task_done(task_id, "pass", report)
            print(f"Marked task {task_id} as pass.")

if __name__ == "__main__":
    main()
