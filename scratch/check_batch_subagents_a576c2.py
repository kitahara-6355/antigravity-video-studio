import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "000 (agents/orchestration/mark_tasks_p27_multi14.py)": "79e28b71-55c6-4c46-aa77-9517ab44e314",
        "001 (agents/orchestration/generate_subagent_reports.py)": "9e75c680-d3bb-48c4-baaf-33f5b7c72cfe",
        "002 (minimal_telop_generator.py)": "e3239dea-eb0a-41e6-b0ab-5a1ac8db008b",
        "003 (aligned_preview_generator.py)": "1454e421-cce6-4583-97c2-3b52aaccd8df",
        "004 (usage_tracker/api_usage_tracker.py)": "33ddcbab-5041-4344-b839-c3b79c7e0f9a",
        "005 (archives/archive_stable_v3.0_20260118_0953/video_processor.py)": "b9a93c94-c70e-4918-b6bf-e153dfa4393e",
        "006 (template_recommender.py)": "936ffec2-2d72-419c-a7dc-cf7fd66f096a",
        "007 (verify_e2e_workflow.py)": "1a57450d-2524-495a-9bcd-1de9861d01fb",
        "008 (subtitle_engine/whisper_subprocess.py)": "b6bd3437-f76e-4cc7-9476-e1ffba49426c",
        "009 (routers/youtube_upload.py)": "8e69df81-2949-48c5-9848-3aff9b00f203"
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
                # 簡易ステータスチェック
                is_completed = any(x in last_response for x in ["完了", "報告", "success", "PASS", "マーク"])
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
