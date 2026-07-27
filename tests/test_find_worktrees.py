import sys
import runpy
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# プロジェクトルートを Python パスに追加
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.scratch.find_worktrees import (
    get_worktree_lines,
    find_matching_worktrees,
    GitCommandError,
    DEFAULT_CONV_ID
)

def test_find_matching_worktrees():
    lines = [
        "C:/worktrees/conv-1  [conv-1]",
        "C:/worktrees/conv-2  [conv-2]",
        "C:/worktrees/conv-3  [conv-3]"
    ]
    # マッチするものがある場合
    res = find_matching_worktrees(lines, "conv-2")
    assert res == ["C:/worktrees/conv-2  [conv-2]"]
    
    # マッチするものがない場合
    res = find_matching_worktrees(lines, "conv-9")
    assert res == []

def test_get_worktree_lines_success():
    # verifies: REQ-WTREE-01
    mock_stdout = "line1\nline2\n"
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.returncode = 0
    
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        lines = get_worktree_lines()
        mock_run.assert_called_once_with(["git", "worktree", "list"], capture_output=True, text=True, timeout=10)
        assert lines == ["line1", "line2"]

def test_get_worktree_lines_git_failure():
    # verifies: REQ-WTREE-02
    mock_res = MagicMock()
    mock_res.returncode = 128
    mock_res.stderr = "fatal: not a git repository"
    
    with patch("subprocess.run", return_value=mock_res):
        with pytest.raises(GitCommandError) as exc_info:
            get_worktree_lines()
        assert exc_info.value.args == ("Git command failed: fatal: not a git repository", 128)

def test_get_worktree_lines_git_not_found():
    # verifies: REQ-WTREE-02
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(GitCommandError) as exc_info:
            get_worktree_lines()
        assert exc_info.value.args == ("Git command not found. Please install git.", 1)

def test_get_worktree_lines_timeout():
    # verifies: REQ-WTREE-01
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 10)):
        with pytest.raises(GitCommandError) as exc_info:
            get_worktree_lines()
        assert exc_info.value.args == ("Git command timed out.", 1)

def test_find_worktrees_runpy_default_args(capsys):
    # verifies: REQ-WTREE-02
    sys.modules.pop("backend.scratch.find_worktrees", None)
    
    mock_stdout = (
        "C:/Users/PC_User/.../a9736a64-a242-485f-942e-bf8476d21fa6/some-worktree  [some-worktree]\n"
    )
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.returncode = 0
    
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        with patch.object(sys, "argv", ["find_worktrees.py"]):
            runpy.run_module("backend.scratch.find_worktrees", run_name="__main__")
            
    captured = capsys.readouterr()
    assert "Total worktrees: 1" in captured.out
    assert "Found 1 matching worktrees:" in captured.out
    assert "a9736a64-a242-485f-942e-bf8476d21fa6" in captured.out

def test_find_worktrees_runpy_custom_args(capsys):
    sys.modules.pop("backend.scratch.find_worktrees", None)
    
    mock_stdout = (
        "C:/Users/PC_User/.../custom-conv-id/some-worktree  [some-worktree]\n"
    )
    mock_res = MagicMock()
    mock_res.stdout = mock_stdout
    mock_res.returncode = 0
    
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        with patch.object(sys, "argv", ["find_worktrees.py", "custom-conv-id"]):
            runpy.run_module("backend.scratch.find_worktrees", run_name="__main__")
            
    captured = capsys.readouterr()
    assert "Total worktrees: 1" in captured.out
    assert "Found 1 matching worktrees:" in captured.out
    assert "custom-conv-id" in captured.out

def test_find_worktrees_runpy_failure(capsys):
    # verifies: REQ-WTREE-02
    sys.modules.pop("backend.scratch.find_worktrees", None)
    
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with patch.object(sys, "argv", ["find_worktrees.py"]):
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_module("backend.scratch.find_worktrees", run_name="__main__")
            assert exc_info.value.code == 1
            
    captured = capsys.readouterr()
    assert "Git command not found. Please install git." in captured.err




