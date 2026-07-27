import os

log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\a9bbb47d-ad0e-4f34-823b-4433375b866b\.system_generated\tasks\task-1701.log"
if os.path.exists(log_path):
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # 失敗部分のインデックスを探す
    fail_idx = -1
    for idx, line in enumerate(lines):
        if "FAILURES" in line or "FAILED" in line:
            fail_idx = idx
            break
            
    if fail_idx != -1:
        print("".join(lines[max(0, fail_idx - 10) : min(len(lines), fail_idx + 150)]))
    else:
        print("FAILURES keyword not found. Last 100 lines:")
        print("".join(lines[-100:]))
else:
    print("Log not found")
