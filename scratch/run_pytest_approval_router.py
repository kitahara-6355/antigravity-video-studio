import subprocess
import os
import sys

def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = r"c:\Users\PC_User\Desktop\script\video-automation\backend"
    env["ISOLATE_BACKEND"] = "1"
    env["COVERAGE_CORE"] = "pytrace"
    
    test_path = "tests/test_approval_router.py"
    print(f"Running pytest via coverage on {test_path}...")
    try:
        res = subprocess.run(
            ["pytest", "-o", "testpaths=tests/test_approval_router.py", "-p", "no:cov", test_path, "-v"],
            env=env,
            cwd=r"c:\Users\PC_User\Desktop\script\video-automation\backend",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )
        print("Exit Code:", res.returncode)
        print("=== STDOUT ===")
        print(res.stdout)
        print("=== STDERR ===")
        print(res.stderr)
        
        if res.returncode == 0 or res.returncode == 2:
            res_rep = subprocess.run(
                ["coverage", "report", "-m"],
                env=env,
                cwd=r"c:\Users\PC_User\Desktop\script\video-automation\backend",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            print("=== COVERAGE REPORT ===")
            print(res_rep.stdout)
            print(res_rep.stderr)
    except subprocess.TimeoutExpired as e:
        print("Timeout Expired! pytest hung!")
        print("STDOUT so far:")
        print(e.stdout if e.stdout else "No stdout")
        print("STDERR so far:")
        print(e.stderr if e.stderr else "No stderr")

if __name__ == "__main__":
    main()
