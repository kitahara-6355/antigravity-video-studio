import json
from pathlib import Path

log_path = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\db22b2b2-ab28-4523-ae06-ad1dc20423e8\.system_generated\logs\transcript.jsonl")

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
    # Step 141 または最新のコマンド実行結果の出力を表示
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
                print(f"Model Content: {content}")
            tool_calls = step.get('tool_calls', [])
            if tool_calls:
                print(f"Tool Calls: {tool_calls}")
else:
    print("Log not found")
