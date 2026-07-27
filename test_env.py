import importlib.util

def check_import(name):
    if importlib.util.find_spec(name):
        print(f"[OK] {name} is installed")
    else:
        print(f"[FAIL] {name} is NOT installed")

check_import("moviepy")
check_import("whisper")
check_import("pydub")
print("Python verification finished.")
