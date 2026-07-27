import json

log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\2302cf45-1f68-4208-9603-df67394b7bc9\.system_generated\logs\transcript.jsonl"

try:
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    print(f"Total lines: {len(lines)}")
    for line in lines[-10:]:
        try:
            data = json.loads(line)
            print(f"[{data.get('type')}] - {data.get('status')}")
            content = data.get('content', '')
            if content:
                print(f"  Content: {content[:300]}...")
            tool_calls = data.get('tool_calls', [])
            if tool_calls:
                print(f"  Tool calls: {tool_calls}")
        except Exception as e:
            print(f"Failed to parse line: {e}")
except Exception as e:
    print(f"Failed to read log: {e}")
