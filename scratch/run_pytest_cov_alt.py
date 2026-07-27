import subprocess
import os

def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = r"c:\Users\PC_User\Desktop\script\video-automation;c:\Users\PC_User\Desktop\script\video-automation\backend"
    
    res = subprocess.run(
        ["pytest", "--cov=routers.admin_analytics_router", "tests/test_admin_analytics_router.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    print("Exit Code:", res.returncode)
    print("=== STDOUT ===")
    print(res.stdout)
    print("=== STDERR ===")
    print(res.stderr)

if __name__ == "__main__":
    main()
