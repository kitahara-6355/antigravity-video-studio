import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_2a82da-bug_hunter-000 (flash_assign_subagents_8.py)": "37b7bd66-5ec2-49b5-9331-6eeb2875d86b",
        "T-batch_2a82da-bug_hunter-001 (wave_scheduler.py)": "b08a185d-9b30-416e-8f7d-ac18971cf306",
        "T-batch_2a82da-bug_hunter-002 (verify_council_v2.py)": "a278b84d-0f13-414a-952a-67e5ed4c7709",
        "T-batch_2a82da-bug_hunter-003 (run_session_end.py)": "eebd69d2-722e-4c9b-b8e5-0ccfa58451ce",
        "T-batch_2a82da-bug_hunter-004 (_e2e_cycle3.py)": "c657e287-c518-4524-b89f-eb50cefe1d7c",
        "T-batch_2a82da-bug_hunter-005 (council_graph.py)": "7824e96b-b7a2-4b07-88e0-558e90a7867e"
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
