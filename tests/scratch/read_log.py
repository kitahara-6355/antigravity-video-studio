import json
from pathlib import Path

def main():
    log_path = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\ecf8e7d2-8173-4818-8ac8-0b410cd129a0\.system_generated\logs\transcript.jsonl")
    if not log_path.exists():
        print(f"Log path not found: {log_path}")
        return
        
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for line in lines:
        try:
            data = json.loads(line)
            step_idx = data.get("step_index")
            if step_idx is not None and 10100 <= step_idx <= 10153:
                src = data.get("source")
                t = data.get("type")
                if t in ("USER_INPUT", "PLANNER_RESPONSE"):
                    content = data.get("content", "")
                    if content:
                        print(f"[{step_idx}] {src} ({t}):")
                        print(content[:1500])
                        print("-" * 50)
        except Exception as e:
            pass

if __name__ == "__main__":
    main()
