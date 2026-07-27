import subprocess

def main():
    cmd = [
        "python",
        "scratch/mark_task.py",
        "T-batch_e75bd1-bug_hunter-000",
        "pass",
        '{"message": "verify_council_v2.py bug fixing and verification tests passed"}'
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print("Exit Code:", res.returncode)
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)

if __name__ == "__main__":
    main()
