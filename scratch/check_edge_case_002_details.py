# -*- coding: utf-8 -*-
import json
import os

cid = "413dedca-d443-4aef-8fae-883c406289aa"
log_path = f"C:\\Users\\PC_User\\.gemini\\antigravity\\brain\\{cid}\\.system_generated\\logs\\transcript.jsonl"

if not os.path.exists(log_path):
    print("Log not found.")
    exit(1)

with open(log_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"=== edge_case-002 details (Total: {len(lines)}) ===")

# 最新の5行について、完全にパースしてダンプ
for i in range(max(0, len(lines)-5), len(lines)):
    line = lines[i]
    try:
        data = json.loads(line)
        print(f"\n--- STEP {i} ---")
        print(f"Source: {data.get('source')}")
        print(f"Type: {data.get('type')}")
        print(f"Status: {data.get('status')}")
        if data.get("content"):
            print("Content:")
            print(data.get("content"))
        if data.get("tool_calls"):
            print("Tool Calls:")
            for tc in data["tool_calls"]:
                print(f"  Name: {tc.get('name')}")
                print(f"  Arguments: {json.dumps(tc.get('arguments'), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Error parsing line {i}: {e}")
