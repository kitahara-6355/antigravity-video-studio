import subprocess

def main():
    tasks = [
        ("T-batch_e75bd1-test_weaver-000", "agents/supervisor.py test coverage tests passed"),
        ("T-batch_e75bd1-thumbnail-001", "project_archiver.py thumbnail generation and verification tests passed"),
    ]
    for task_id, msg in tasks:
        cmd = [
            "python",
            "scratch/mark_task.py",
            task_id,
            "pass",
            f'{{"message": "{msg}"}}'
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print(f"Task {task_id}: Exit Code {res.returncode}")
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)

if __name__ == "__main__":
    main()
