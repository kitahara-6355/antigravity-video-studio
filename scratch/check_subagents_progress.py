import json
import os
from pathlib import Path

def main():
    # 1. Run manage_subagents list conceptually, but we can also scan the active directories
    # The active subagents' worktrees are stored under .system_generated/worktrees/ or their logs in brain/
    # Actually, we can check the subagent logs under C:\Users\PC_User\.gemini\antigravity\brain\
    # Let's list all directories in the brain folder
    brain_dir = Path(r"C:\Users\PC_User\.gemini\antigravity\brain")
    if not brain_dir.exists():
        print(f"Brain dir not found: {brain_dir}")
        return

    # We want to identify subagents associated with the current session.
    # The current session ID is 065194c8-04f3-4708-9c18-94ccadff1f41.
    # Any subagent directory will have a transcript.jsonl under .system_generated/logs/transcript.jsonl
    # Let's check subagent directories (they are UUID-like names or subagent-* in worktrees).
    # Wait, the conversation IDs of subagents are UUIDs like c247824c-713e-4f05-83f4-cbf87b21dd82.
    # So their transcripts are in C:\Users\PC_User\.gemini\antigravity\brain\<conv_id>\.system_generated\logs\transcript.jsonl
    
    print("Scanning brain directories for subagents...")
    subagent_states = []
    
    for item in brain_dir.iterdir():
        if not item.is_dir():
            continue
        # Check if transcript.jsonl exists
        log_file = item / ".system_generated" / "logs" / "transcript.jsonl"
        if not log_file.exists():
            continue
            
        # Read the first few lines to get the initial prompt and target module
        # and read the last few lines to see if it completed.
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines:
                continue
                
            # Parse first line to get role and prompt
            first_step = json.loads(lines[0])
            # The prompt is usually in the USER_INPUT type or initial prompt
            # Let's search for "initialPrompt" or instructions
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
            
            # Let's extract target_module and role
            # Often, the first step contains initialPrompt if it's the system setting it up,
            # or the user input contains it.
            # Let's search for keywords in initial_prompt
            if "対象モジュール:" in initial_prompt:
                # Find the line with "対象モジュール:"
                for p_line in initial_prompt.split("\n"):
                    if "対象モジュール:" in p_line:
                        target_module = p_line.split("対象モジュール:")[1].strip()
                        
            # Determine status by scanning backwards
            status = "running"
            result_summary = ""
            
            # We look for "完遂", "完了", "SUCCESS", "FAIL", "PASS" or last response from the model
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
                # Check if last response contains indicators of completion
                # For example, "完了しました", "テストはすべてPASS", etc.
                lower_resp = last_model_response.lower()
                if "完了" in last_model_response or "pass" in lower_resp or "success" in lower_resp:
                    status = "completed_pass"
                elif "fail" in lower_resp or "エラー" in last_model_response or "失敗" in last_model_response:
                    status = "completed_fail"
                result_summary = last_model_response[:200].replace("\n", " ")
                
            subagent_states.append({
                "conversation_id": item.name,
                "target_module": target_module,
                "status": status,
                "last_response": result_summary
            })
        except Exception as e:
            # print(f"Error parsing {item.name}: {e}")
            pass

    print(f"\nFound {len(subagent_states)} subagent transcripts:")
    for state in subagent_states:
        # Only show relevant subagents (not our own conversation which is dynamic)
        curr_id = os.environ.get("CONVERSATION_ID", "ddc38d7b-e9dc-4aaf-b3d4-0642d02ef4b1")
        if state["conversation_id"] == curr_id:
            continue
        print(f"- ID: {state['conversation_id']}")
        print(f"  Module: {state['target_module']}")
        print(f"  Status: {state['status']}")
        print(f"  Last Response: {state['last_response'][:120]}...")
        print()

if __name__ == "__main__":
    main()
