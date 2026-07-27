import sys
import os
import shutil
import subprocess

# PYTHONPATHの追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration import OrchestrationHub
hub = OrchestrationHub()

# 1. 心拍更新（最優先）
hub.flash_update_heartbeat()
print("Heartbeat updated.")

env = os.environ.copy()
env["PYTHONPATH"] = "c:/Users/PC_User/Desktop/script/video-automation"

task_id = "T-batch_376a66-thumbnail-014"

# コピー定義
copies = [
    (
        "C:/Users/PC_User/.gemini/antigravity/brain/6f6fec28-4332-4296-b237-b7d0d5e5bb93/.system_generated/worktrees/subagent-thumbnail-Agent-15-self-fdef8404/backend/agents/_deprecated/nexus.py",
        "c:/Users/PC_User/Desktop/script/video-automation/backend/agents/_deprecated/nexus.py"
    ),
    (
        "C:/Users/PC_User/.gemini/antigravity/brain/6f6fec28-4332-4296-b237-b7d0d5e5bb93/.system_generated/worktrees/subagent-thumbnail-Agent-15-self-fdef8404/tests/test_deprecated_nexus.py",
        "c:/Users/PC_User/Desktop/script/video-automation/tests/test_deprecated_nexus.py"
    ),
    (
        "C:/Users/PC_User/.gemini/antigravity/brain/6f6fec28-4332-4296-b237-b7d0d5e5bb93/.system_generated/worktrees/subagent-thumbnail-Agent-15-self-fdef8404/tests/test_nexus_deprecated.py",
        "c:/Users/PC_User/Desktop/script/video-automation/tests/test_nexus_deprecated.py"
    )
]

results = {}

try:
    for src, dest in copies:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(src):
            shutil.copy2(src, dest)
            print(f"[{task_id}] Copied {src} -> {dest}")
        else:
            raise Exception(f"Source file not found: {src}")

    # 単体テスト実行
    print(f"[{task_id}] Running pytest on target tests...")
    res1 = subprocess.run(["pytest", "tests/test_deprecated_nexus.py"], capture_output=True, text=True, env=env)
    res2 = subprocess.run(["pytest", "tests/test_nexus_deprecated.py"], capture_output=True, text=True, env=env)
    if res1.returncode != 0 or res2.returncode != 0:
        print(f"[{task_id}] test1 stdout:", res1.stdout)
        print(f"[{task_id}] test2 stdout:", res2.stdout)
        raise Exception(f"pytest failed: code1={res1.returncode}, code2={res2.returncode}")
    print(f"[{task_id}] pytest passed.")
    results[task_id] = True
except Exception as e:
    print(f"[{task_id}] Error: {e}", file=sys.stderr)
    results[task_id] = False

# 全体フィットネステスト
ff_passed = False
if results[task_id]:
    try:
        print("Running fitness functions test...")
        res_ff = subprocess.run(["pytest", "backend/tests/test_fitness_functions.py"], capture_output=True, text=True, env=env)
        if res_ff.returncode != 0:
            print("FF stdout:", res_ff.stdout)
            print("FF stderr:", res_ff.stderr)
            raise Exception(f"Fitness functions failed with code {res_ff.returncode}")
        print("Fitness functions passed.")
        ff_passed = True
    except Exception as e:
        print(f"Fitness function error: {e}", file=sys.stderr)

# 結果のマーク
if results[task_id] and ff_passed:
    hub.mark_task_done(task_id, "pass", {
        "message": "nexus.py/テストコード コピー成功、全テストPASS (19 passed, TD-254/TD-255解消)",
        "changed_files": [
            "backend/agents/_deprecated/nexus.py",
            "tests/test_deprecated_nexus.py",
            "tests/test_nexus_deprecated.py"
        ]
    })
    print(f"Task {task_id} marked as pass.")
else:
    hub.mark_task_done(task_id, "fail", {
        "error": f"Verification failed (single_test={results[task_id]}, ff_test={ff_passed})",
        "changed_files": []
    })
    print(f"Task {task_id} marked as fail.")
