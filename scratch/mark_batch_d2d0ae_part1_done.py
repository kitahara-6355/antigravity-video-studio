import subprocess

def main():
    tasks = [
        ("T-batch_d2d0ae-test_weaver-000", "scratch/check_queue.py test coverage tests passed"),
        ("T-batch_d2d0ae-thumbnail-000", "inspect_video.py thumbnail generation and verification tests passed"),
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
