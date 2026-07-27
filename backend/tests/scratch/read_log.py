import json
import os
import sys

DEFAULT_LOG_PATH = r"C:\Users\PC_User\.gemini\antigravity\brain\46d6d33a-3bbe-48a1-a6d9-c2e5a85b157a\.system_generated\logs\transcript.jsonl"


def read_user_inputs(log_path: str) -> list[dict]:
    """指定されたログファイルから USER_INPUT タイプの行を読み込んでリストを返します。"""
    if not os.path.exists(log_path):
        print("Log path does not exist!")
        return []

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print(f"Total lines in log: {len(lines)}")
    user_inputs = []
    for line in lines:
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get('type') == 'USER_INPUT':
                user_inputs.append(data)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            pass
    return user_inputs


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG_PATH
    inputs = read_user_inputs(log_path)
    print(f"Found {len(inputs)} user inputs:")
    for idx, ui in enumerate(inputs):
        content = ui.get('content') or ""
        print(f"User Input {idx}: {content[:300].replace('\n', ' ')}")
