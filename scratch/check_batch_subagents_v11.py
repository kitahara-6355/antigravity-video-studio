import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_034cb4-bug_hunter-000 (verify_council_v2.py)": "4166483a-2043-4407-9d0e-d9a173d5109d",
        "T-batch_034cb4-bug_hunter-001 (wave_scheduler.py)": "99585ced-4fd3-43e9-823a-aa6aa81fc4ad",
        "T-batch_034cb4-bug_hunter-002 (flash_assign_subagents_8.py)": "9b1f8bc3-5613-46fb-83dc-5fa8a98b8a2a",
        "T-batch_034cb4-bug_hunter-003 (run_session_end.py)": "8497720f-9167-49d9-9f8c-e2ed9b7f1f32",
        "T-batch_034cb4-bug_hunter-004 (tests/_e2e_cycle3.py)": "dbf77936-88df-4a33-a17b-c8c2332d95b0",
        "T-batch_034cb4-bug_hunter-005 (agents/council_graph.py)": "447d44ab-2183-4aef-a5ee-4523e1494342"
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
                summary = "\n".join(lines_resp[:8])
                if len(lines_resp) > 8:
                    summary += "\n  ... (truncated)"
                print(f"  Status Check (Last Response Preview):\n{summary}")
            else:
                print("  No planner response found.")
        except Exception as e:
            print(f"  Error: {e}")
        print()

if __name__ == "__main__":
    main()
