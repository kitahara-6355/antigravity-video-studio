import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "T-batch_034cb4-bug_hunter-000 (scratch/get_next_batch.py)": "126de810-4cb3-4d6f-948b-522db70eceb4",
        "T-batch_034cb4-bug_hunter-001 (error_reporter.py)": "f1ef8f42-5028-4f71-9059-88d5e7651a02",
        "T-batch_034cb4-bug_hunter-002 (plugins/report_generator_plugin.py)": "05c96165-0f3a-4b01-9cd2-d72b36331b42",
        "T-batch_034cb4-bug_hunter-003 (agents/director.py)": "360cce0d-ec82-456d-9391-ca04bf86765d",
        "T-batch_034cb4-bug_hunter-004 (agents/orchestration/learning_integration.py)": "21b81ffa-f793-4c47-927d-feda99c3aa4c",
        "T-batch_034cb4-bug_hunter-005 (service_container.py)": "701830cf-7275-41a2-9538-20e2241faaf5"
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
                # 簡易ステータスチェック: 完了メッセージが最後のレスポンスに入っているか
                is_completed = "完了" in last_response or "報告" in last_response or "success" in last_response.lower()
                if is_completed:
                    completed_count += 1
                    status_str = "🟢 COMPLETED"
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
        
    print(f"=== Summary: {completed_count}/{len(subagents)} subagents completed. ===")

if __name__ == "__main__":
    main()
