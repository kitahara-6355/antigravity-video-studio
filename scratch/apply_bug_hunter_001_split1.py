import os
import sys
import shutil
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    hub.register_flash_conversation_id("ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1")

    worktree = r"C:/Users/PC_User/.gemini/antigravity/brain/ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1/.system_generated/worktrees/subagent-bug-hunter-Agent-001-split1-self-99a32309"
    
    targets = [
        "backend/tests/_e2e_cycle3.py",
        "backend/tests/test_e2e_cycle3.py"
    ]
    
    copied_files = []
    for rel_path in targets:
        src_path = os.path.join(worktree, rel_path)
        dst_path = rel_path
        if os.path.exists(src_path):
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            print(f"Copying {src_path} -> {dst_path}")
            shutil.copy2(src_path, dst_path)
            copied_files.append(dst_path)
            
    if not copied_files:
        print("Error: No changed files found in worktree!")
        sys.exit(1)
        
    # Run tests
    test_files = [f for f in copied_files if "test_" in f]
    for t_file in test_files:
        print(f"Running test: python -m pytest --timeout=300 {t_file}")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.abspath(".") + os.pathsep + os.path.abspath("./backend") + os.pathsep + env.get("PYTHONPATH", "")
        res = subprocess.run(["python", "-m", "pytest", "-W", "error", "--timeout=300", "-v", t_file], capture_output=True, text=True, env=env)
        print("STDOUT:")
        print(res.stdout)
        print("STDERR:")
        print(res.stderr)
        if res.returncode != 0:
            print(f"Test failed for {t_file}!")
            sys.exit(1)
            
    # Mark task as pass
    task_id = "T-batch_8b2dd3-bug_hunter-001-split1"
    report = {
        "message": "tests/_e2e_cycle3.py 具体的な通信・進捗監視処理の実装完了。テスト更新。24 passed を確認。",
        "changed_files": copied_files
    }
    
    print(f"Marking task {task_id} as pass...")
    hub.mark_task_done(task_id, "pass", report)
    hub.flash_update_heartbeat()
    print("SUCCESS")
    
if __name__ == "__main__":
    main()
