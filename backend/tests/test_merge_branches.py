import os
import sys
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest

import backend.scratch.merge_branches as merge_branches

def test_get_worktrees_dir_worktrees_parent(tmp_path):
    """親ディレクトリ名が 'worktrees' の場合のテスト"""
    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir()
    subdir = worktrees_dir / "subdir"
    subdir.mkdir()
    fake_file = subdir / "merge_branches.py"
    
    with patch("backend.scratch.merge_branches.os.path.abspath", return_value=str(fake_file)):
        res = merge_branches.get_worktrees_dir()
        assert res == worktrees_dir

def test_get_worktrees_dir_system_generated_exists(tmp_path):
    """親ディレクトリ以下に '.system_generated/worktrees' が存在する場合のテスト"""
    project_dir = tmp_path
    sys_gen = project_dir / ".system_generated"
    worktrees_dir = sys_gen / "worktrees"
    worktrees_dir.mkdir(parents=True)
    
    subdir = project_dir / "subdir"
    subdir.mkdir()
    fake_file = subdir / "merge_branches.py"
    
    with patch("backend.scratch.merge_branches.os.path.abspath", return_value=str(fake_file)):
        res = merge_branches.get_worktrees_dir()
        assert res == worktrees_dir

def test_get_worktrees_dir_fallback_exists():
    """親ディレクトリには見つからず、フォールバックパスが存在する場合のテスト"""
    with patch("backend.scratch.merge_branches.os.path.abspath", return_value="/nonexistent/file.py"), \
         patch("backend.scratch.merge_branches.os.path.exists", return_value=True):
        res = merge_branches.get_worktrees_dir()
        expected = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\0723d652-a51c-45e1-a10b-442254c17079\.system_generated\worktrees")
        assert res == expected
        assert isinstance(res, Path)

def test_get_worktrees_dir_none():
    """親ディレクトリにもフォールバックにも見つからない場合のテスト"""
    with patch("backend.scratch.merge_branches.os.path.abspath", return_value="/nonexistent/file.py"), \
         patch("backend.scratch.merge_branches.os.path.exists", return_value=False):
        res = merge_branches.get_worktrees_dir()
        assert res is None

def test_run_tests_success():
    """品質テストが成功（returncode=0）する場合のテスト"""
    with patch("backend.scratch.merge_branches.subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "Test Passed"
        mock_run.return_value = mock_process
        
        res = merge_branches.run_tests()
        assert res is True
        mock_run.assert_called_once()

def test_run_tests_failure():
    """品質テストが失敗（returncode!=0）する場合のテスト"""
    with patch("backend.scratch.merge_branches.subprocess.run") as mock_run:
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = "Test Failed"
        mock_process.stderr = "Error output"
        mock_run.return_value = mock_process
        
        res = merge_branches.run_tests()
        assert res is False
        mock_run.assert_called_once()

def test_main_no_worktrees():
    """worktrees_dir が見つからない場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir:
        mock_get_dir.return_value = None
        
        # 早期リターンして何も起こらないこと
        with patch("backend.scratch.merge_branches.os.listdir") as mock_listdir:
            merge_branches.main()
            mock_listdir.assert_not_called()

def test_main_worktrees_not_exists():
    """worktrees_dir は返るが存在しない場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir:
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = False
        mock_get_dir.return_value = mock_dir
        
        with patch("backend.scratch.merge_branches.os.listdir") as mock_listdir:
            merge_branches.main()
            mock_listdir.assert_not_called()

def test_main_no_branches():
    """マージ対象のブランチが存在しない場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        # subagent- で始まらない、または suffix が8文字でないディレクトリ
        mock_listdir.return_value = ["other-directory", "subagent-no-hex", "subagent-1234567"]
        
        merge_branches.main()
        mock_run.assert_not_called()

def test_main_merge_success():
    """ブランチのマージが成功し、テストもパスする場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run, \
         patch("backend.scratch.merge_branches.run_tests") as mock_run_tests:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        # 2つのマージ対象ブランチ
        mock_listdir.return_value = ["subagent-feature-abcdef01", "subagent-bugfix-12345678"]
        
        # git merge の結果 (成功)
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "Fast-forward merged"
        mock_run.return_value = mock_process
        
        # テストもパスする
        mock_run_tests.return_value = True
        
        merge_branches.main()
        
        # 2つのブランチそれぞれに対して git merge が実行されたことを確認
        # ソートされるので 12345678 が先、abcdef01 が後
        expected_calls = [
            call(["git", "merge", "--no-edit", "subagent-bugfix-12345678"], capture_output=True, text=True),
            call(["git", "merge", "--no-edit", "subagent-feature-abcdef01"], capture_output=True, text=True),
        ]
        mock_run.assert_has_calls(expected_calls)
        assert mock_run_tests.call_count == 2

def test_main_merge_failed():
    """git merge が失敗して abort する場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run, \
         patch("backend.scratch.merge_branches.run_tests") as mock_run_tests:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        mock_listdir.return_value = ["subagent-feature-abcdef01"]
        
        # git merge が失敗する
        mock_process_fail = MagicMock()
        mock_process_fail.returncode = 1
        mock_process_fail.stdout = "Conflict detected"
        mock_run.return_value = mock_process_fail
        
        merge_branches.main()
        
        # git merge --abort が呼ばれることを確認
        mock_run.assert_any_call(["git", "merge", "--abort"])
        mock_run_tests.assert_not_called()

def test_main_quality_test_failed():
    """マージ後の品質テストが失敗し、ロールバックされる場合のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run, \
         patch("backend.scratch.merge_branches.run_tests") as mock_run_tests:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        mock_listdir.return_value = ["subagent-feature-abcdef01"]
        
        # git merge 自体は成功する
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = "Fast-forward merged"
        mock_run.return_value = mock_process
        
        # 品質テストは失敗する
        mock_run_tests.return_value = False
        
        merge_branches.main()
        
        # git reset --hard HEAD~1 が呼ばれることを確認
        mock_run.assert_any_call(["git", "reset", "--hard", "HEAD~1"])

def test_script_execution():
    """__main__ としてスクリプトが実行された場合のテスト"""
    # 実際の main が実行されるが、get_worktrees_dir() が None を返して安全に早期リターンすることを期待する
    # get_worktrees_dir が None を返すように、os.path.exists などを偽装しておく
    with patch("backend.scratch.merge_branches.os.path.exists", return_value=False):
        runpy.run_module("backend.scratch.merge_branches", run_name="__main__")

class MockSubdir(str):
    def split(self, sep=None, maxsplit=-1):
        if sep == "-":
            return ["subagent"]
        return super().split(sep, maxsplit)

def test_main_split_length_less_than_two():
    """parts の長さが 2 未満になる特殊なケースのテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        mock_subdir = MockSubdir("subagent-special")
        mock_listdir.return_value = [mock_subdir]
        
        merge_branches.main()
        mock_run.assert_not_called()

def test_main_suffix_not_length_eight():
    """suffix の長さが 8 以外の時のテスト"""
    with patch("backend.scratch.merge_branches.get_worktrees_dir") as mock_get_dir, \
         patch("backend.scratch.merge_branches.os.listdir") as mock_listdir, \
         patch("backend.scratch.merge_branches.subprocess.run") as mock_run:
        
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = True
        mock_get_dir.return_value = mock_dir
        
        mock_listdir.return_value = ["subagent-short-12345"]
        
        merge_branches.main()
        mock_run.assert_not_called()
