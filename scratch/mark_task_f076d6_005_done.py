import subprocess

def print_exit_code(returncode: int) -> None:
    """終了コードを表示します。"""
    print("Exit Code:", returncode)

def print_stdout(stdout: str) -> None:
    """標準出力を表示します。"""
    print("STDOUT:", stdout)

def print_stderr(stderr: str) -> None:
    """標準エラー出力を表示します。"""
    print("STDERR:", stderr)

def build_mark_task_arguments() -> list[str]:
    """タスク完了マークコマンドの引数リストを構築します。"""
    return [
        "python",
        "scratch/mark_task.py",
        "T-batch_e8ab91-thumbnail-000",
        "pass",
        '{"message": "combined_overlay.py thumbnail generation, atomic write, pixel validation, and strict aspect ratio tests passed successfully."}'
    ]

def execute_subprocess_command(command_arguments: list[str]) -> subprocess.CompletedProcess:
    """指定されたコマンドをサブプロセスとして実行します。"""
    return subprocess.run(
        command_arguments,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

def display_execution_result(execution_result: subprocess.CompletedProcess) -> None:
    """コマンド実行結果（終了コード、標準出力、標準エラー出力）を表示します。"""
    print_exit_code(execution_result.returncode)
    print_stdout(execution_result.stdout)
    print_stderr(execution_result.stderr)

def main() -> None:
    """メインのエントリポイント関数。"""
    command_arguments = build_mark_task_arguments()
    execution_result = execute_subprocess_command(command_arguments)
    display_execution_result(execution_result)

if __name__ == "__main__":
    main()
