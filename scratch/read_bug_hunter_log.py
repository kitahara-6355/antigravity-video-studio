import json
import os

log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\0df435eb-ab69-4f89-b83b-765c67fb90e1\.system_generated\logs\transcript.jsonl"

if not os.path.exists(log_path):
    print(f"Log path does not exist: {log_path}")
else:
    print(f"Log path exists: {log_path}, size: {os.path.getsize(log_path)} bytes")
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    for i in range(max(0, len(lines)-5), len(lines)):
        try:
            step = json.loads(lines[i])
            print(f"\n--- STEP {step.get('step_index')} (type: {step.get('type')}, status: {step.get('status')}) ---")
            content = step.get("content", "")
            if len(content) > 300:
                content = content[:300] + "... (truncated)"
            print(content)
            if "tool_calls" in step:
                print(f"Tool calls: {len(step['tool_calls'])}")
                for tc in step["tool_calls"]:
                    print(f"  - {tc.get('name')} | {tc.get('arguments', {}).get('toolAction')}")
        except Exception as e:
            print(f"Error parsing line {i}: {e}")
