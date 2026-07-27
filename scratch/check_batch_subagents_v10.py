import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_d899d9-bug_hunter-000 (routers/pipeline_default_states.py)": "db2fdbcb-d134-4bd9-8efd-687d062f364a",
        "T-batch_d899d9-bug_hunter-001 (mark_tasks_p27_multi13.py)": "4f86ecf0-b38d-4f1a-bd01-2a5341c3fb58",
        "T-batch_d899d9-bug_hunter-002 (quality_gate_ai.py)": "57192e87-687d-4448-b089-a63cb47c995a",
        "T-batch_d899d9-bug_hunter-003 (services/tdr_resolver.py)": "2396446c-50bb-49a8-bb96-a56b1841c2e9",
        "T-batch_d899d9-bug_hunter-004 (utils/json_safe_io.py)": "b264862b-8e71-4600-86b1-f3a749006738",
        "T-batch_d899d9-bug_hunter-005 (dispatch_enhancer.py)": "749f2d5a-8839-444e-b8d8-0f9d6f4eb348"
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
