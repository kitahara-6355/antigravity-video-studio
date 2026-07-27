import json
import os
import sys

log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\logs\transcript.jsonl"

try:
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        if len(lines) <= 786:
            raise IndexError("Log file has fewer lines than expected (787 lines minimum required).")
            
        line = lines[786]
        data = json.loads(line)
        
        if not isinstance(data, dict):
            raise TypeError("Parsed JSON is not a dictionary.")
            
        content = data.get("content", "")
        if not isinstance(content, str):
            raise TypeError("'content' key is not a string.")
            
        print("Content preview:")
        print(content[:2000])
    else:
        print("Not found")
except IndexError as e:
    sys.stderr.write(f"IndexError: {str(e)}\n")
    sys.exit(1)
except json.JSONDecodeError as e:
    sys.stderr.write(f"JSONDecodeError: {str(e)}\n")
    sys.exit(1)
except TypeError as e:
    sys.stderr.write(f"TypeError: {str(e)}\n")
    sys.exit(1)
except UnicodeDecodeError as e:
    sys.stderr.write(f"UnicodeDecodeError: {str(e)}\n")
    sys.exit(1)
except PermissionError as e:
    sys.stderr.write(f"PermissionError: {str(e)}\n")
    sys.exit(1)
except FileNotFoundError as e:
    sys.stderr.write(f"FileNotFoundError: {str(e)}\n")
    sys.exit(1)
except OSError as e:
    sys.stderr.write(f"OSError: {str(e)}\n")
    sys.exit(1)
except Exception as e:
    sys.stderr.write(f"Unexpected error: {str(e)}\n")
    sys.exit(1)
