import os
import subprocess
import logging
from typing import TypedDict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# デフォルトのワークツリーパスを環境変数から取得し、存在しない場合はカレントディレクトリを使用します。
DEFAULT_WORKTREE_PATH = os.environ.get(
    "ANTIGRAVITY_WORKTREE_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)


class GitInfoResult(TypedDict):
    exists: bool
    status_stdout: str
    status_stderr: str
    log_stdout: str
    log_stderr: str
    error: Optional[str]


@dataclass
class GitWorktreeConfig:
    worktree_path: str
    log_count: int = 3


class GitWorktreeChecker:
    """Git ワークツリーの状態とログを取得・検証・表示するクラス"""

    def __init__(self, config: GitWorktreeConfig) -> None:
        self.config = config

    def check_exists(self) -> bool:
        """ワークツリーパスの存在確認"""
        return os.path.exists(self.config.worktree_path)

    def fetch_git_info(self) -> GitInfoResult:
        """Git status および log の情報を取得"""
        result: GitInfoResult = {
            "exists": False,
            "status_stdout": "",
            "status_stderr": "",
            "log_stdout": "",
            "log_stderr": "",
            "error": None
        }

        if not self.check_exists():
            result["error"] = f"Path does not exist: {self.config.worktree_path}"
            return result

        result["exists"] = True

        # Git statusの取得
        try:
            status_proc = subprocess.run(
                ["git", "status"],
                cwd=self.config.worktree_path,
                capture_output=True,
                text=True,
                check=True
            )
            result["status_stdout"] = status_proc.stdout
            result["status_stderr"] = status_proc.stderr
        except FileNotFoundError as e:
            logger.error("git command not found on the system during status check.", exc_info=True)
            result["error"] = f"FileNotFoundError: {str(e)}"
            return result
        except PermissionError as e:
            logger.error("Permission denied when running git status.", exc_info=True)
            result["error"] = f"PermissionError: {str(e)}"
            return result
        except subprocess.SubprocessError as e:
            logger.error(f"Subprocess error during git status: {str(e)}", exc_info=True)
            result["error"] = f"SubprocessError: {str(e)}"
            return result

        # Git logの取得
        try:
            log_proc = subprocess.run(
                ["git", "log", f"-n{self.config.log_count}", "--oneline"],
                cwd=self.config.worktree_path,
                capture_output=True,
                text=True,
                check=True
            )
            result["log_stdout"] = log_proc.stdout
            result["log_stderr"] = log_proc.stderr
        except FileNotFoundError as e:
            logger.error("git command not found on the system during log fetch.", exc_info=True)
            result["error"] = f"FileNotFoundError: {str(e)}"
        except PermissionError as e:
            logger.error("Permission denied when running git log.", exc_info=True)
            result["error"] = f"PermissionError: {str(e)}"
        except subprocess.SubprocessError as e:
            logger.error(f"Subprocess error during git log: {str(e)}", exc_info=True)
            result["error"] = f"SubprocessError: {str(e)}"

        return result

    def display_info(self, info: GitInfoResult) -> None:
        """取得した Git 情報をフォーマットして標準出力に表示"""
        if not info["exists"]:
            print(f"Error: {info['error']}")
            return

        if info["error"]:
            print(f"Partial Error: {info['error']}")

        print("=== Git Status ===")
        print(info["status_stdout"] or "No status output.")
        if info["status_stderr"]:
            print(f"Stderr: {info['status_stderr']}")

        print("\n=== Git Log ===")
        print(info["log_stdout"] or "No log output.")
        if info["log_stderr"]:
            print(f"Stderr: {info['log_stderr']}")


def check_worktree_git(worktree_path: str) -> None:
    """互換性のためのエントリーポイント"""
    config = GitWorktreeConfig(worktree_path=worktree_path)
    checker = GitWorktreeChecker(config)
    info = checker.fetch_git_info()
    checker.display_info(info)


def main() -> None:
    """メインエントリーポイント"""
    check_worktree_git(DEFAULT_WORKTREE_PATH)


if __name__ == "__main__":  # pragma: no cover
    main()
