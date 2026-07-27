import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    subagents = {
        "000 (agents/orchestration/mark_tasks_p27_multi14.py)": "b7e4ea48-a0af-4cee-b1c0-a49aaebcdb66",
        "001 (agents/orchestration/generate_subagent_reports.py)": "834456eb-659b-4530-8689-48288a399f7b",
        "002 (verify_collaboration_api.py)": "113f5cbf-fdd9-408a-b453-fe43bc4c54a7",
        "003 (cleanup_disk.py)": "ff100028-e50c-44ab-b1cb-95eba69b740f",
        "004 (preview_system.py)": "30c3deb1-2480-4da8-928c-5428660d1439",
        "005 (color_grading.py)": "66b13fbc-61cf-49ac-aa4d-c2f99734e2df",
        "006 (scripts/gen_session9.py)": "35d5f3ee-e0b9-48a0-9939-8c4a4fdc1533",
        "007 (plugins/smart_cut_plugin.py)": "c8b4dfff-8914-44a9-9155-82ac209a4fb0",
        "008 (scratch/submit_batch.py)": "ec56b7e3-1db4-45d6-9ef7-d221df23deb6",
        "009 (verify_full_system.py)": "42bf0926-eaa6-4fc5-a01d-2a0d38c1b83b"
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
                # 簡易ステータスチェック: "完了報告"、"完了しました" または pytest などの合格単語が含まれているか
                # ただし誤検知を防ぐため、明らかに「テスト実行を待っています」などの場合は除外したいが、
                # ここでは最後の100文字程度をみて簡易判定
                is_completed = "完了" in last_response or "報告" in last_response or "success" in last_response.lower()
                # 誤検知除外パターン
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
