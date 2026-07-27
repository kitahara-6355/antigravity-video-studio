import os
import subprocess
import sys

root_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\0e95a029-d93d-49ca-9da7-a1a8aaf448fd\.system_generated\worktrees\subagent-self-improve-Agent-self-5894bc8e"
backend_dir = os.path.join(root_dir, "backend")

env = os.environ.copy()
env['PYTHONPATH'] = f"{backend_dir};{root_dir};" + env.get('PYTHONPATH', '')

python_exe = r"c:/Users/PC_User/Desktop/script/vault-environments/.venv/Scripts/python.exe"

if len(sys.argv) > 1:
    args = [python_exe, "-m", "pytest"] + sys.argv[1:]
else:
    args = [python_exe, "-m", "pytest", "backend/tests/"]

print("Running command:", " ".join(args))
print("PYTHONPATH:", env['PYTHONPATH'])

result = subprocess.run(args, env=env, cwd=root_dir)
sys.exit(result.returncode)
