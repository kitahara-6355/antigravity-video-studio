import json
import os
import time
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    if not brain_dir.exists():
        print(f"Brain dir not found: {brain_dir}")
        return

    print("Scanning brain directories for recent subagents...")
    now = time.time()
    recent_subagents = []
    
    for item in brain_dir.iterdir():
        if not item.is_dir():
            continue
        log_file = item / ".system_generated" / "logs" / "transcript.jsonl"
        if not log_file.exists():
            continue
            
        # check modification time
        mtime = os.path.getmtime(log_file)
        # 過去20分間に更新されたログを対象とする
        if now - mtime > 1200:
            continue
            
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                continue
                
            role = ""
            target_module = ""
            initial_prompt = ""
            for line in lines[:10]:
                try:
                    data = json.loads(line)
                    if data.get("type") == "USER_INPUT":
                        initial_prompt = data.get("content", "")
                        break
                except Exception:
                    pass
            
            for p_line in initial_prompt.split("\n"):
                if "対象:" in p_line:
                    target_module = p_line.split("対象:")[1].strip()
                    break
                elif "対象モジュール:" in p_line:
                    target_module = p_line.split("対象モジュール:")[1].strip()
                    break
            
            status = "running"
            result_summary = ""
            last_model_response = ""
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    if data.get("source") == "MODEL" and data.get("type") == "PLANNER_RESPONSE":
                        content = data.get("content", "")
                        if content:
                            last_model_response = content
                            break
                except Exception:
                    pass
            
            if last_model_response:
                lower_resp = last_model_response.lower()
                if "完了" in last_model_response or "pass" in lower_resp or "success" in lower_resp:
                    status = "completed_pass"
                elif "fail" in lower_resp or "エラー" in last_model_response or "失敗" in last_model_response:
                    status = "completed_fail"
                result_summary = last_model_response[:200].replace("\n", " ")
                
            recent_subagents.append({
                "conversation_id": item.name,
                "target_module": target_module,
                "status": status,
                "last_response": result_summary,
                "mtime": mtime
            })
        except Exception as e:
            pass

    # Sort by mtime descending
    recent_subagents.sort(key=lambda x: x["mtime"], reverse=True)
    
    curr_id = os.environ.get("CONVERSATION_ID", "ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1")
    count = 0
    for state in recent_subagents:
        if state["conversation_id"] == curr_id:
            continue
        print(f"- ID: {state['conversation_id']}")
        print(f"  Module: {state['target_module']}")
        print(f"  Status: {state['status']}")
        print(f"  Last Response: {state['last_response'][:120]}...")
        print()
        count += 1
        
    print(f"Total recent subagents found: {count}")

if __name__ == "__main__":
    main()
