import json
import os
from pathlib import Path

def main():
    mappings = {
        "Agent 0 (flash_assign_subagents_8)": "443a4ef9-bf1e-4df0-95cc-507ad0962cc7",
        "Agent 1 (error_reporter)": "6899e643-b550-4220-a014-16d9ee022ae5",
        "Agent 2 (learning_integration)": "d887fa4d-3127-4f34-bc1f-f9e62ea1de22",
        "Agent 3 (wave_scheduler)": "65414d4b-8e69-4523-a956-a1632b53b713",
        "Agent 4 (council_graph)": "f9918046-01cc-495c-82b7-d3fde031591e",
        "Agent 5 (mark_tasks_p27_batch_449dfb)": "77db9624-6f27-435a-8525-2b590935d856"
    }

    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    
    print("=== Current Batch Subagents Status ===")
    for name, conv_id in mappings.items():
        log_path = brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        print(f"[{name}] ID: {conv_id}")
        
        if not log_path.exists():
            print("  Status: NOT STARTED (Log not found)")
            print("-" * 50)
            continue
            
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            if not lines:
                print("  Status: EMPTY LOG")
                print("-" * 50)
                continue
                
            # ステータスの判定
            status = "RUNNING"
            last_msg = ""
            
            # 後ろからスキャンして、完了報告等のキーワードを探す
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    if data.get("source") == "MODEL" and data.get("type") == "PLANNER_RESPONSE":
                        content = data.get("content", "")
                        if content:
                            last_msg = content
                            break
                except Exception:
                    pass
            
            if last_msg:
                lower_msg = last_msg.lower()
                if "完了" in last_msg or "pass" in lower_msg or "success" in lower_msg:
                    status = "COMPLETED_PASS"
                elif "fail" in lower_msg or "エラー" in last_msg or "失敗" in last_msg:
                    status = "COMPLETED_FAIL"
                    
            print(f"  Status: {status}")
            if last_msg:
                # 最後のメッセージの先頭150文字を表示
                msg_preview = last_msg.strip().replace("\n", " ")
                print(f"  Last Response: {msg_preview[:150]}...")
        except Exception as e:
            print(f"  Error reading log: {e}")
            
        print("-" * 50)

if __name__ == "__main__":
    main()
