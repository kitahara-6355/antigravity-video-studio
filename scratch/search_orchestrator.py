import os

file_path = "backend/agents/orchestration/orchestrator.py"
if os.path.exists(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # submit_batch_report の定義を探す
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "def submit_batch_report" in line or "def end_session" in line or "def flash_session_end" in line:
            print(f"Line {idx+1}: {line.strip()}")
            # その後15行を表示
            for offset in range(1, 20):
                if idx + offset < len(lines):
                    print(f"  {lines[idx+offset]}")
else:
    print(f"File not found: {file_path}")
