import os
import json

transcript_path = r"C:\Users\PC_User\.gemini\antigravity\brain\7e26fad8-fbf2-439d-883c-82a9eb6bc0e3\.system_generated\logs\transcript_full.jsonl"
if os.path.exists(transcript_path):
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if idx == 309: # Line 310
                    data = json.loads(line)
                    tool_calls = data.get("tool_calls", [])
                    for tc in tool_calls:
                        if tc.get("name") == "invoke_subagent":
                            args = tc.get("args")
                            if isinstance(args, str):
                                args = json.loads(args)
                            subagents = args.get("Subagents", [])
                            # 最初のエージェントの Prompt だけ詳しく出力してみる
                            if subagents:
                                first_sa = subagents[0]
                                print(f"Role: {first_sa.get('Role')}")
                                print(f"Prompt:\n{first_sa.get('Prompt')}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("Transcript not found.")
