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
            "id": "T-batch_95c7b3-bug_hunter-001",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\e7d5ee29-c861-487d-a471-85a31bff83d0",
            "files": [
                ("verify_full_system.py", "backend/verify_full_system.py"),
                ("test_verify_full_system.py", "backend/tests/test_verify_full_system.py")
            ],
            "tests": ["backend/tests/test_verify_full_system.py"],
            "msg": "Phase 33 verify_full_system.py bug fix completed."
        },
        {
            "id": "T-batch_95c7b3-bug_hunter-002",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-95c7b3-bug-hunter-002-self-f4507e6b",
            "files": [
                ("backend/branding/evolution_log.json", "backend/branding/evolution_log.json")
            ],
            "tests": [],
            "msg": "Phase 33 plugins/smart_cut_plugin.py bug fix completed (evolution_log.json updated)."
        },
        {
            "id": "T-batch_95c7b3-bug_hunter-003",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\ec61f06b-99d7-4ce0-81a2-99cca27a2147",
            "files": [],
            "tests": ["backend/tests/test_gen_session9.py"],
            "msg": "Phase 33 scripts/gen_session9.py bug fix completed."
        },
        {
            "id": "T-batch_95c7b3-bug_hunter-004",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-95c7b3-bug-hunter-004-self-0e0378f0",
            "files": [],
            "tests": ["backend/tests/test_mark_tasks_p27_multi14.py"],
            "msg": "Phase 33 mark_tasks_p27_multi14.py bug fix completed."
        },
        {
            "id": "T-batch_95c7b3-bug_hunter-005",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\790758f1-d405-4a07-86c1-ef5fe4705438\.system_generated\worktrees\subagent-bug-hunter-Agent-T-batch-95c7b3-bug-hunter-005-self-58b1cd5a",
            "files": [],
            "tests": ["backend/tests/test_generate_subagent_reports.py"],
            "msg": "Phase 33 generate_subagent_reports.py bug fix completed."
        },
        {
            "id": "T-batch_95c7b3-bug_hunter-007",
            "wt": r"C:\Users\PC_User\.gemini\antigravity\brain\f959a1e0-92bb-4f0e-a120-203b32b30219",
            "files": [
                ("verify_collaboration_api.py", "backend/verify_collaboration_api.py"),
                ("test_verify_collaboration_api.py", "backend/tests/test_shared/test_verify_collaboration_api.py")
            ],
            "tests": ["backend/tests/test_shared/test_verify_collaboration_api.py"],
            "msg": "Phase 33 verify_collaboration_api.py bug fix completed."
        }
    ]

    for config in agents_config:
        task_id = config["id"]
        wt_path = config["wt"]
        print(f"\n=== Syncing {task_id} ===")
        
        for src_rel, dest_rel in config["files"]:
            src_path = os.path.join(wt_path, src_rel)
            if not os.path.exists(src_path):
                src_path = os.path.join(wt_path, src_rel.replace("backend/", ""))
                
            dest_path = os.path.join(PROJECT_ROOT, dest_rel)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {src_path} -> {dest_path}")

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
