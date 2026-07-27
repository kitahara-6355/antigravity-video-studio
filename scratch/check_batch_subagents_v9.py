import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_06b8f5-bug_hunter-000 (wave_scheduler.py)": "41d11fb6-e5f7-42f2-9447-9667b9ee480b",
        "T-batch_06b8f5-bug_hunter-001 (verify_council_v2.py)": "8a538d97-a608-4d60-86f1-3c5fca004d79",
        "T-batch_06b8f5-bug_hunter-002 (flash_assign_subagents_8.py)": "72d6169a-415f-4724-a11f-32da73572ba3",
        "T-batch_06b8f5-bug_hunter-003 (run_session_end.py)": "83683996-d901-46d9-b32b-ad26a4d1e296",
        "T-batch_06b8f5-bug_hunter-004 (_e2e_cycle3.py)": "7080f60b-12dd-48bf-bc3d-0da1e8688e6c",
        "T-batch_06b8f5-bug_hunter-005 (council_graph.py)": "ea879c3c-cda1-4477-8361-11540ddb097c"
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
