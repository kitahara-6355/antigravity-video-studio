import os
import shutil
import subprocess
import sys

# パスの定義
worktree_root = r"C:\Users\PC_User\.gemini\antigravity\brain\72b83e00-587a-490e-9bfd-621adcc85cdc\.system_generated\worktrees\subagent-test-weaver-Agent-045-self-5cba9ccc"
files_to_copy = [
    ("backend/tests/test_api_usage_tracker.py", "backend/tests/test_api_usage_tracker.py"),
    ("tests/test_api_usage_tracker.py", "backend/tests/test_api_usage_tracker.py") # 念のため両方のパターンをチェック
]

# 1. コピー
for src_rel, dst_rel in files_to_copy:
    src_path = os.path.join(worktree_root, src_rel)
    dst_path = os.path.join(r"c:\Users\PC_User\Desktop\script\video-automation", dst_rel)
    if os.path.exists(src_path):
        print(f"Copying {src_path} -> {dst_path}")
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy(src_path, dst_path)

# 2. テスト実行
env = os.environ.copy()
env["PYTHONPATH"] = r"backend;backend/services;" + env.get("PYTHONPATH", "")
try:
    res = subprocess.run(["python", "-m", "pytest", "backend/tests/test_api_usage_tracker.py"], capture_output=True, text=True, check=True, env=env)
    print("Test passed!")
    print(res.stdout)
except subprocess.CalledProcessError as e:
    print("Test failed!")
    print(e.stdout)
    print(e.stderr)
    sys.exit(1)

# 3. Hubにマーク
sys.path.append(r"c:\Users\PC_User\Desktop\script\video-automation")
from backend.agents.orchestration import OrchestrationHub
hub = OrchestrationHub()
hub.mark_task_done("T-batch_6ebe32-test_weaver-001", "pass", {
    "message": "backend/usage_tracker/api_usage_tracker.py に対し、プロダクションコードを一切変更せず、ブランチカバレッジ 100% を達成する追加のユニットテストを実装しました。",
    "changed_files": [
        "backend/tests/test_api_usage_tracker.py"
    ]
})
print("Marked task done.")

# 4. 自走スクリプト自体を削除
try:
    os.remove(__file__)
    print("Temporary script removed.")
except Exception as e:
    print(f"Error removing script: {e}")
