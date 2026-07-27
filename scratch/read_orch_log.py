import os

log_path = "logs/weakness_orchestrator.log"
if os.path.exists(log_path):
    print(f"Log path exists, size: {os.path.getsize(log_path)} bytes")
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    # Print the last 15 lines
    for i in range(max(0, len(lines)-15), len(lines)):
        print(lines[i].strip())
else:
    print("Orchestrator log file does not exist")
