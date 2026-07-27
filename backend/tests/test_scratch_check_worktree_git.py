import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import logging

# プロジェクトルートディレクトリを sys.path に追加
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# テスト対象モジュールのインポート
try:
    from backend.scratch import check_worktree_git as target_module
except ImportError:
    import check_worktree_git as target_module


def test_classes_and_types_exist():
    assert hasattr(target_module, "GitInfoResult")
    assert hasattr(target_module, "GitWorktreeConfig")
    assert hasattr(target_module, "GitWorktreeChecker")


def test_git_worktree_config_init():
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path", log_count=5)
    assert config.worktree_path == "/dummy/path"
    assert config.log_count == 5


@patch("os.path.exists")
def test_check_exists(mock_exists):
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    mock_exists.return_value = True
    assert checker.check_exists() is True
    
    mock_exists.return_value = False
    assert checker.check_exists() is False


@patch("os.path.exists")
def test_fetch_git_info_path_not_exist(mock_exists):
    mock_exists.return_value = False
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    info = checker.fetch_git_info()
    assert info["exists"] is False
    assert "Path does not exist" in info["error"]


@patch("os.path.exists")
@patch("subprocess.run")
def test_fetch_git_info_success(mock_run, mock_exists):
    mock_exists.return_value = True
    
    # git status と git log のモック戻り値
    mock_status = MagicMock()
    mock_status.stdout = "On branch main\nnothing to commit"
    mock_status.stderr = ""
    
    mock_log = MagicMock()
    mock_log.stdout = "a1b2c3d Commit message"
    mock_log.stderr = ""
    
    mock_run.side_effect = [mock_status, mock_log]
    
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    info = checker.fetch_git_info()
    assert info["exists"] is True
    assert info["status_stdout"] == "On branch main\nnothing to commit"
    assert info["log_stdout"] == "a1b2c3d Commit message"
    assert info["error"] is None


@pytest.mark.parametrize(
    "exception_cls, expected_err_prefix",
    [
        (FileNotFoundError("git not found"), "FileNotFoundError"),
        (PermissionError("denied"), "PermissionError"),
        (subprocess.SubprocessError("sub err"), "SubprocessError"),
    ]
)
@patch("os.path.exists")
@patch("subprocess.run")
def test_fetch_git_info_status_exceptions(mock_run, mock_exists, exception_cls, expected_err_prefix):
    mock_exists.return_value = True
    mock_run.side_effect = exception_cls
    
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    info = checker.fetch_git_info()
    assert info["exists"] is True
    assert expected_err_prefix in info["error"]


@pytest.mark.parametrize(
    "exception_cls, expected_err_prefix",
    [
        (FileNotFoundError("git not found"), "FileNotFoundError"),
        (PermissionError("denied"), "PermissionError"),
        (subprocess.SubprocessError("sub err"), "SubprocessError"),
    ]
)
@patch("os.path.exists")
@patch("subprocess.run")
def test_fetch_git_info_log_exceptions(mock_run, mock_exists, exception_cls, expected_err_prefix):
    mock_exists.return_value = True
    
    # status は成功し、log で例外が発生するように設定
    mock_status = MagicMock()
    mock_status.stdout = "On branch main"
    mock_status.stderr = ""
    
    mock_run.side_effect = [mock_status, exception_cls]
    
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    info = checker.fetch_git_info()
    assert info["exists"] is True
    assert info["status_stdout"] == "On branch main"
    assert expected_err_prefix in info["error"]


@patch("builtins.print")
def test_display_info(mock_print):
    config = target_module.GitWorktreeConfig(worktree_path="/dummy/path")
    checker = target_module.GitWorktreeChecker(config)
    
    # パスが存在しない場合
    info_not_exist = {
        "exists": False,
        "status_stdout": "",
        "status_stderr": "",
        "log_stdout": "",
        "log_stderr": "",
        "error": "Path does not exist"
    }
    checker.display_info(info_not_exist)
    mock_print.assert_any_call("Error: Path does not exist")
    
    # 一部エラーがある場合
    info_partial_error = {
        "exists": True,
        "status_stdout": "On branch main",
        "status_stderr": "status stderr",
        "log_stdout": "log stdout",
        "log_stderr": "log stderr",
        "error": "SubprocessError: log failed"
    }
    checker.display_info(info_partial_error)
    mock_print.assert_any_call("Partial Error: SubprocessError: log failed")
    mock_print.assert_any_call("=== Git Status ===")
    mock_print.assert_any_call("On branch main")
    mock_print.assert_any_call("Stderr: status stderr")
    mock_print.assert_any_call("\n=== Git Log ===")
    mock_print.assert_any_call("log stdout")
    mock_print.assert_any_call("Stderr: log stderr")


@patch("os.path.exists")
@patch("subprocess.run")
def test_check_worktree_git_wrapper(mock_run, mock_exists):
    mock_exists.return_value = True
    
    mock_status = MagicMock()
    mock_status.stdout = "On branch main"
    mock_status.stderr = ""
    
    mock_log = MagicMock()
    mock_log.stdout = "a1b2c3d Commit"
    mock_log.stderr = ""
    
    mock_run.side_effect = [mock_status, mock_log]
    
    # 呼び出しが正常に行われること
    target_module.check_worktree_git("/dummy/path")


@patch("os.path.exists")
@patch("subprocess.run")
def test_main(mock_run, mock_exists):
    mock_exists.return_value = True
    
    mock_status = MagicMock()
    mock_status.stdout = "On branch main"
    mock_status.stderr = ""
    
    mock_log = MagicMock()
    mock_log.stdout = "a1b2c3d Commit"
    mock_log.stderr = ""
    
    mock_run.side_effect = [mock_status, mock_log]
    
    # main の実行確認
    target_module.main()
