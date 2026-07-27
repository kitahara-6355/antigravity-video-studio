import os
import json

log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\4b875004-a889-452d-a119-f60fc343bbd6\.system_generated\logs\transcript.jsonl"
with open(log_path, "r", encoding="utf-8") as f:
    lines = f.readlines()
print(f"Total lines: {len(lines)}")
for i in range(max(0, len(lines)-10), len(lines)):
    line = lines[i].strip()
    if not line:
        continue
    step = json.loads(line)
    print(f"\n=== STEP {step.get('step_index')} (source: {step.get('source')} type: {step.get('type')}) ===")
    if "tool_calls" in step:
        for tc in step["tool_calls"]:
            print(f"  Tool: {tc.get('name')}")
            print(f"  Args: {tc.get('arguments')}")
    if step.get("type") == "RUN_COMMAND" and "content" in step:
        print(f"  Result content: {step.get('content')[:300]}")
    if step.get("source") == "MODEL" and step.get("type") == "PLANNER_RESPONSE" and "content" in step and step.get("content"):
         print(f"  Text content: {step.get('content')[:300]}")
