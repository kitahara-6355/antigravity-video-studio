import json
import os

msg_path = "backend/agents/orchestration/message_box.jsonl"
if os.path.exists(msg_path):
    print(f"Message box size: {os.path.getsize(msg_path)} bytes")
    with open(msg_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    # Print the last 5 messages
    for i in range(max(0, len(lines)-10), len(lines)):
        raw_line = lines[i].strip()
        print(f"--- Line {i} ---")
        print(raw_line[:300])
        try:
            msg = json.loads(raw_line)
            if isinstance(msg, dict):
                print(f"Time: {msg.get('timestamp')} | From: {msg.get('sender')} | Task: {msg.get('task_id')} | Status: {msg.get('status')}")
            else:
                print("Not a dictionary:", msg)
        except Exception as e:
            print(f"Error: {e}")
else:
    print("Message box does not exist")
