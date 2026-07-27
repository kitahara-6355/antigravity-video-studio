import subprocess

def main():
    cmd = [
        "python",
        "scratch/mark_task.py",
        "T-batch_e75bd1-test_weaver-001",
        "pass",
        '{"message": "tests/_test_3tier_fallback.py test coverage tests passed"}'
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print("Exit Code:", res.returncode)
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)

if __name__ == "__main__":
    main()
