import sys
import os
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from path_resolver import backend_dir, brain_dir, project_root

# 会話 UUID は当時のもの。親（brain/）は解決に通してある。
src_file = str(brain_dir() / "432d8506-5ff4-46ae-8b90-2469a0dd7aed" / "test_mark_tasks_001.py")
dest_file = str(backend_dir() / "tests" / "test_mark_tasks_001.py")

try:
    # 1. ファイルの上書きコピー
    if os.path.exists(src_file):
        shutil.copyfile(src_file, dest_file)
        print(f"Successfully copied {src_file} to {dest_file}")
    else:
        print(f"ERROR: Source file {src_file} does not exist!")
        sys.exit(1)
        
    # 2. measure_coverage.py の再実行
    # Windowsなので shell=True を使用して python コマンドを呼び出す
    print("Running scripts/measure_coverage.py...")
    # カレントディレクトリの設定
    cwd = str(project_root())
    # PYTHONPATH の設定
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(cwd, "backend") + os.pathsep + env.get("PYTHONPATH", "")
    
    result = subprocess.run(
        ["python", "scripts/measure_coverage.py"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=600  # 10分タイムアウト
    )
    
    print("STDOUT:")
    print(result.stdout)
    print("STDERR:")
    print(result.stderr)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 0:
        print("RECHECK_SUCCESS")
    else:
        print("RECHECK_FAILED")
        sys.exit(1)

except Exception as e:
    import traceback
    print(f"ERROR: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
