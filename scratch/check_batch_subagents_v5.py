import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_b57b54-bug_hunter-000 (verify_council_v2.py)": "89f5f1ce-caf9-44a8-b84e-01861d2646ac",
        "T-batch_b57b54-bug_hunter-001 (flash_assign_subagents_8.py)": "22aba8f5-3cbc-49a3-b05a-d42a99ddc526",
        "T-batch_b57b54-bug_hunter-002 (wave_scheduler.py)": "45ed9cdc-651a-41dd-b0fd-153dc5c59b75",
        "T-batch_b57b54-bug_hunter-003 (run_session_end.py)": "5c2fd013-2fc0-4ae6-b23b-83ad3623b05d",
        "T-batch_b57b54-bug_hunter-004 (_e2e_cycle3.py)": "f0954ea9-ef62-4cf2-899d-35ba383cd81a",
        "T-batch_b57b54-bug_hunter-005 (council_graph.py)": "993c26f7-7053-45a0-839d-235265fd9595"
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
