import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "000 (scratch/submit_batch.py)": "f5c0d66c-72ab-464e-a717-46ea2bd95b30",
        "001 (verify_full_system.py)": "e7d5ee29-c861-487d-a471-85a31bff83d0",
        "002 (plugins/smart_cut_plugin.py)": "36968590-9a44-462c-9aff-3fb375070522",
        "003 (scripts/gen_session9.py)": "ec61f06b-99d7-4ce0-81a2-99cca27a2147",
        "004 (agents/orchestration/mark_tasks_p27_multi14.py)": "07d321be-57c6-4397-ac4b-c673b60ee17f",
        "005 (agents/orchestration/generate_subagent_reports.py)": "4524fe9b-2dac-4e6b-b38d-77b3efad5beb",
        "006 (agents/orchestration/cleanup_disk.py)": "ff75b1a6-a3c9-45f0-95a8-105ad8420ba8",
        "007 (verify_collaboration_api.py)": "f959a1e0-92bb-4f0e-a120-203b32b30219",
        "008 (preview_system.py)": "359561a0-f306-47cb-ac42-a815309973ec",
        "009 (color_grading.py)": "0989a00d-6aba-4232-af6d-4f9c50abf115"
    }
    
    completed_count = 0
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
                is_completed = "完了" in last_response or "報告" in last_response or "success" in last_response.lower()
                if "待ってい" in last_response or "waiting" in last_response.lower() or "実行中" in last_response:
                    is_completed = False

                if is_completed:
                    completed_count += 1
                    status_str = "🟢 COMPLETED / WAITING"
                else:
                    status_str = "🟡 RUNNING"
                
                lines_resp = last_response.strip().split("\n")
                summary = "\n".join(lines_resp[:6])
                if len(lines_resp) > 6:
                    summary += "\n  ... (truncated)"
                print(f"  Status: {status_str}\n  Last Response Preview:\n{summary}")
            else:
                print("  Status: 🟡 RUNNING (No planner response found)")
        except Exception as e:
            print(f"  Error: {e}")
        print()
        
    print(f"=== Summary: {completed_count}/{len(subagents)} subagents completed/waiting. ===")

if __name__ == "__main__":
    main()
