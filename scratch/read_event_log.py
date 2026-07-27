import os

log_path = "backend/agents/orchestration/event_log.jsonl"
if os.path.exists(log_path):
    print(f"Event log path exists, size: {os.path.getsize(log_path)} bytes")
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    for i in range(max(0, len(lines)-15), len(lines)):
        print(lines[i].strip())
else:
    print("Event log file does not exist")
