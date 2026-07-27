import subprocess
import os

def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = r"c:\Users\PC_User\Desktop\script\video-automation;c:\Users\PC_User\Desktop\script\video-automation\backend"
    
    test_path = "backend/tests/test_verify_council_v2.py"
    print(f"Running pytest on {test_path}...")
    try:
        res = subprocess.run(
            ["pytest", "-v", test_path],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        print("Exit Code:", res.returncode)
        print("=== STDOUT ===")
        print(res.stdout)
        print("=== STDERR ===")
        print(res.stderr)
    except subprocess.TimeoutExpired as e:
        print("Timeout Expired! pytest hung!")
        print("STDOUT so far:")
        print(e.stdout.decode('utf-8', errors='ignore') if e.stdout else "No stdout")
        print("STDERR so far:")
        print(e.stderr.decode('utf-8', errors='ignore') if e.stderr else "No stderr")

if __name__ == "__main__":
    main()
