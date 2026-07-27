import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_74e4bc-bug_hunter-000 (wave_scheduler.py)": "edddbf52-2208-4b5b-83a1-d9000cc535ca",
        "T-batch_74e4bc-bug_hunter-001 (flash_assign_subagents_8.py)": "b61fe13b-05ac-40ed-93a4-ee802377832b",
        "T-batch_74e4bc-bug_hunter-003 (run_session_end.py)": "271425f6-fb85-4c6a-8278-8f6d0f4a992e",
        "T-batch_74e4bc-bug_hunter-004 (_e2e_cycle3.py)": "108dae35-e447-49d6-804b-1b6bb51afe7c",
        "T-batch_74e4bc-bug_hunter-005 (council_graph.py)": "339783e9-28d1-4fb9-af9b-9583f4cfb931"
    }
    
    for label, sub_id in subagents.items():
        log_file = brain_dir / sub_id / ".system_generated" / "logs" / "transcript.jsonl"
        print(f"=== {label} [ID: {sub_id}] ===")
        if not log_file.exists():
            print("  Log file not found.")
            print()
            continue
            
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                print("  Log file is empty.")
                print()
                continue
                
            last_response = ""
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    if data.get("source") == "MODEL" and data.get("type") == "PLANNER_RESPONSE":
                        last_response = data.get("content", "")
                        if last_response:
                            break
                except Exception:
                    pass
            
            if last_response:
                lines_resp = last_response.strip().split("\n")
                summary = "\n".join(lines_resp[:5])
                if len(lines_resp) > 5:
                    summary += "\n  ... (truncated)"
                print(f"  Status Check (Last Response Preview):\n{summary}")
            else:
                print("  No planner response found.")
        except Exception as e:
            print(f"  Error: {e}")
        print()

if __name__ == "__main__":
    main()
