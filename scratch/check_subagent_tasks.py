import json
from pathlib import Path

def check_subagent(sub_id, name):
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    log_file = brain_dir / sub_id / ".system_generated" / "logs" / "transcript.jsonl"
    print(f"=== {name} ({sub_id}) ===")
    if not log_file.exists():
        print("Log not found")
        return
    
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    print(f"Total steps: {len(lines)}")
    recent_steps = lines[-8:] if len(lines) >= 8 else lines
    for line in recent_steps:
        try:
            data = json.loads(line)
            step_idx = data.get("step_index", "?")
            source = data.get("source", "?")
            step_type = data.get("type", "?")
            status = data.get("status", "?")
            content = data.get("content", "")
            
            print(f"  Step {step_idx} | Source: {source} | Type: {step_type} | Status: {status}")
            if content:
                print(f"    Content: {content[:150].replace('\n', ' ')}...")
            
            tool_calls = data.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    if tc:
                        t_name = tc.get("name", "?")
                        t_args = tc.get("arguments", {})
                        print(f"    Tool: {t_name} | Args: {str(t_args)[:150]}")
        except Exception as e:
            print(f"  Error parsing line: {e}")
    print()

def main():
    subagents = {
        "Agent 000 (wave_scheduler.py)": "0eb50337-5144-4abf-ae45-fbfde7a1a44a",
        "Agent 004 (run_session_end.py)": "dc66fc4a-4957-4902-9590-9bce5186c4c0",
        "Agent 005 (council_graph.py)": "65c86f00-5ab7-4d69-943e-546990f0480e"
    }
    for name, sub_id in subagents.items():
        check_subagent(sub_id, name)

if __name__ == "__main__":
    main()
