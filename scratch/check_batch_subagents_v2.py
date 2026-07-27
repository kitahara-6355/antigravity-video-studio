import json
import os
from pathlib import Path

def main():
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    if not brain_dir.exists():
        print(f"Brain dir not found: {brain_dir}")
        return

    subagent_ids = [
        "b2914762-fb70-4704-b321-5eb6d1ca5c79",
        "29a3049b-d632-4fc5-a18d-3402e8a4646a"
    ]
    
    results = {}
    for sub_id in subagent_ids:
        log_file = brain_dir / sub_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not log_file.exists():
            results[sub_id] = {"status": "no_log", "module": "unknown", "last_response": "No log file found."}
            continue
            
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                results[sub_id] = {"status": "empty_log", "module": "unknown", "last_response": "Log file is empty."}
                continue
                
            # Get target module
            target_module = "unknown"
            for line in lines[:10]:
                try:
                    data = json.loads(line)
                    if data.get("type") == "USER_INPUT":
                        content = data.get("content", "")
                        for p_line in content.split("\n"):
                            if "対象:" in p_line:
                                target_module = p_line.split("対象:")[1].strip()
                                break
                            elif "対象モジュール:" in p_line:
                                target_module = p_line.split("対象モジュール:")[1].strip()
                                break
                except Exception:
                    pass
            
            # Get last model response
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
            
            status = "running"
            result_summary = "Waiting/Running..."
            if last_model_response:
                lower_resp = last_model_response.lower()
                is_waiting = "wait" in lower_resp or "待機" in last_model_response or "しばらくお待ち" in last_model_response
                if not is_waiting:
                    if "完了" in last_model_response or "pass" in lower_resp or "success" in lower_resp or "報告" in last_model_response:
                        status = "pass"
                    elif "fail" in lower_resp or "エラー" in last_model_response or "失敗" in last_model_response:
                        status = "fail"
                result_summary = last_model_response[:200].replace("\n", " ")
                
            results[sub_id] = {
                "status": status,
                "module": target_module,
                "last_response": result_summary
            }
        except Exception as e:
            results[sub_id] = {"status": "error", "module": "error", "last_response": f"Parsing error: {e}"}

    for sub_id, info in results.items():
        print(f"- ID: {sub_id}")
        print(f"  Module: {info['module']}")
        print(f"  Status: {info['status']}")
        print(f"  Last Response: {info['last_response']}")
        print()

if __name__ == "__main__":
    main()
