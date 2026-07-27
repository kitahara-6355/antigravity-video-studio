import json
import os

def get_default_tdr_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "agents", "memory", "technical_debt_index.json")

def find_tdr_entries(tdr_file_path=None, target_file="cleanup_disk.py"):
    if tdr_file_path is None:
        tdr_file_path = os.environ.get("TDR_INDEX_PATH")
        if not tdr_file_path:
            tdr_file_path = get_default_tdr_path()
            if not os.path.exists(tdr_file_path):
                fallback_path = r"C:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\technical_debt_index.json"
                if os.path.exists(fallback_path):
                    tdr_file_path = fallback_path

    if not os.path.exists(tdr_file_path):
        return []

    try:
        with open(tdr_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from {tdr_file_path}: {e}")
        return []
    except Exception as e:
        print(f"Error reading file {tdr_file_path}: {e}")
        return []

    if not isinstance(data, dict):
        print(f"Invalid data format: expected dict, got {type(data).__name__}")
        return []

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        print(f"Invalid entries format: expected list, got {type(entries).__name__}")
        return []

    matches = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        file_path = entry.get("file_path", "")
        if not isinstance(file_path, str):
            continue
        if target_file in file_path:
            matches.append(entry)

    return matches

def main():
    tdr_path = os.environ.get("TDR_INDEX_PATH") or get_default_tdr_path()
    if not os.path.exists(tdr_path):
        fallback_path = r"C:\Users\PC_User\Desktop\script\video-automation\backend\agents\memory\technical_debt_index.json"
        if os.path.exists(fallback_path):
            tdr_path = fallback_path
        else:
            print("Not found")
            return

    matches = find_tdr_entries(tdr_path)
    print(f"Found {len(matches)} entries matching cleanup_disk.py:")
    for e in matches:
        print(f"  ID: {e.get('debt_id')}, path: {e.get('file_path')}, line: {e.get('line_number')}, status: {e.get('status')}, category: {e.get('category')}")

if __name__ == "__main__":
    main()
