import json
from pathlib import Path

log_path = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\c99da8cf-0858-45c4-b2e7-d8aa16fe10b4\.system_generated\logs\transcript.jsonl")

if log_path.exists():
    steps = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    steps.append(json.loads(line))
                except Exception as e:
                    pass
    
    print(f"Total steps: {len(steps)}")
    # 最新の15ステップを詳細に出力
    for step in steps[-15:]:
        step_idx = step.get('step_index')
        source = step.get('source')
        stype = step.get('type')
        status = step.get('status')
        print(f"--- Step {step_idx} ({source}, {stype}, {status}) ---")
        if stype == "RUN_COMMAND":
            content = step.get('content', '')
            print(f"Command Output:\n{content}")
        elif stype == "PLANNER_RESPONSE":
            content = step.get('content', '')
            if content:
                print(f"Model Content: {content[:300]}")
            tool_calls = step.get('tool_calls', [])
            if tool_calls:
                print(f"Tool Calls: {tool_calls}")
else:
    print("Log not found")
