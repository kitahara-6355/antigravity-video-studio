import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_8ae6aa-bug_hunter-000 (verify_council_v2.py)": "411f46ca-2ce5-4540-8de5-b9879a79a61b",
        "T-batch_8ae6aa-bug_hunter-001 (wave_scheduler.py)": "0eb50337-5144-4abf-ae45-fbfde7a1a44a",
        "T-batch_8ae6aa-bug_hunter-002 (flash_assign_subagents_8.py)": "1399c4d5-e4eb-44ca-bb3f-e5252aa29d99",
        "T-batch_8ae6aa-bug_hunter-003 (_e2e_cycle3.py)": "8317397d-5059-4481-8cf3-715237ceb5b9",
        "T-batch_8ae6aa-bug_hunter-004 (run_session_end.py)": "dc66fc4a-4957-4902-9590-9bce5186c4c0",
        "T-batch_8ae6aa-bug_hunter-005 (council_graph.py)": "65c86f00-5ab7-4d69-943e-546990f0480e"
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
