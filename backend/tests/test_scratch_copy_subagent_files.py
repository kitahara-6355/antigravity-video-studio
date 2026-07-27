# -*- coding: utf-8 -*-
import sys
import os
import pytest
import subprocess
from unittest.mock import patch, MagicMock, call
import runpy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# テスト前にインポートしてパスをダミーに書き換える
from scratch import copy_subagent_files
copy_subagent_files.worktrees_dir = r'C:\dummy\worktrees'
copy_subagent_files.parent_dir = r'C:\dummy\parent'

def test_main_worktrees_dir_not_exists():
    with patch('os.path.exists', return_value=False) as mock_exists:
        with patch('builtins.print') as mock_print:
            copy_subagent_files.main()
            mock_print.assert_any_call('Worktrees directory not found.')
        mock_exists.assert_called_once_with(copy_subagent_files.worktrees_dir)

def test_main_no_matching_worktrees():
    with patch('os.path.exists', return_value=True),          patch('os.listdir', return_value=['wt_unmatched1', 'wt_unmatched2']) as mock_listdir,          patch('builtins.print') as mock_print:
        
        copy_subagent_files.main()
        
        mock_listdir.assert_called_once_with(copy_subagent_files.worktrees_dir)
        mock_print.assert_any_call('Found 0 matching worktrees:')

def test_main_with_matching_worktrees():
    subdirs = ['wt_2b52cbaf', 'wt_unmatched', 'wt_e2393d23']
    
    # git statusの模擬出力
    git_stdout_1 = (
        ' M backend/agents/agent_base.py\n'
        '?? "backend/tests/test_file.py"\n'
        ' M temp_thumbnails/thumbnail.png\n'
        ' M backend/content_dump.txt\n'
        ' M backend/agents/some_dir\n'
    )
    git_stdout_2 = ''
    
    def mock_subprocess_run(cmd, **kwargs):
        cwd = kwargs.get('cwd', '')
        mock_res = MagicMock()
        if 'wt_2b52cbaf' in cwd:
            mock_res.stdout = git_stdout_1
        elif 'wt_e2393d23' in cwd:
            mock_res.stdout = git_stdout_2
        else:
            mock_res.stdout = ''
        mock_res.return_value = 0
        return mock_res

    def mock_isdir(path):
        norm_path = path.replace(chr(92), '/')
        if 'some_dir' in norm_path:
            return True
        return False

    with patch('os.path.exists', return_value=True),          patch('os.listdir', return_value=subdirs),          patch('subprocess.run', side_effect=mock_subprocess_run) as mock_run,          patch('os.path.isdir', side_effect=mock_isdir),          patch('os.makedirs') as mock_makedirs,          patch('shutil.copy2') as mock_copy2,          patch('builtins.print') as mock_print:
         
         copy_subagent_files.main()
         
         assert mock_run.call_count == 2
         
         # コピーの検証
         expected_src_1 = os.path.join(copy_subagent_files.worktrees_dir, 'wt_2b52cbaf', 'backend/agents/agent_base.py')
         expected_dst_1 = os.path.join(copy_subagent_files.parent_dir, 'backend/agents/agent_base.py')
         
         expected_src_2 = os.path.join(copy_subagent_files.worktrees_dir, 'wt_2b52cbaf', 'backend/tests/test_file.py')
         expected_dst_2 = os.path.join(copy_subagent_files.parent_dir, 'backend/tests/test_file.py')
         
         mock_makedirs.assert_any_call(os.path.dirname(expected_dst_1), exist_ok=True)
         mock_makedirs.assert_any_call(os.path.dirname(expected_dst_2), exist_ok=True)
         
         mock_copy2.assert_any_call(expected_src_1, expected_dst_1)
         mock_copy2.assert_any_call(expected_src_2, expected_dst_2)
         
         assert mock_copy2.call_count == 2

def test_module_execution():
    original_worktrees_dir = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\worktrees"
    
    # RuntimeWarningを回避するためにsys.modulesから一時的に削除する
    had_module = 'scratch.copy_subagent_files' in sys.modules
    cached_module = sys.modules.pop('scratch.copy_subagent_files', None)
    
    try:
        with patch('os.path.exists', return_value=False) as mock_exists,              patch('builtins.print') as mock_print:
            runpy.run_module('scratch.copy_subagent_files', run_name='__main__')
            mock_exists.assert_called_with(original_worktrees_dir)
            mock_print.assert_any_call('Worktrees directory not found.')
    finally:
        if had_module and cached_module:
            sys.modules['scratch.copy_subagent_files'] = cached_module

def test_find_matching_worktrees_not_exists():
    from scratch.copy_subagent_files import find_matching_worktrees
    with patch('os.path.exists', return_value=False):
        res = find_matching_worktrees('C:\\nonexistent', [])
        assert res == []

def test_get_changed_files_short_line():
    from scratch.copy_subagent_files import get_changed_files
    mock_res = MagicMock()
    mock_res.stdout = " M file.py\n\n M file2.py\n"
    mock_res.return_value = 0
    with patch('subprocess.run', return_value=mock_res):
        res = get_changed_files('C:\\dummy\\wt')
        assert len(res) == 2
        assert res[0] == ('file.py', ' M')
        assert res[1] == ('file2.py', ' M')

# 新規エラーハンドリング用テストケース
def test_find_matching_worktrees_oserror():
    from scratch.copy_subagent_files import find_matching_worktrees
    with patch('os.path.exists', return_value=True),          patch('os.listdir', side_effect=OSError("Permission denied")),          patch('builtins.print') as mock_print:
        res = find_matching_worktrees('C:\\dummy', ['wt_suffix'])
        assert res == []
        mock_print.assert_any_call("Error listing directory C:\\dummy: Permission denied")

def test_get_changed_files_subprocess_error():
    from scratch.copy_subagent_files import get_changed_files
    with patch('subprocess.run', side_effect=subprocess.SubprocessError("Git error")),          patch('builtins.print') as mock_print:
        res = get_changed_files('C:\\dummy\\wt')
        assert res == []
        mock_print.assert_any_call("Error running git status in C:\\dummy\\wt: Git error")

def test_get_changed_files_filenotfound_error():
    from scratch.copy_subagent_files import get_changed_files
    with patch('subprocess.run', side_effect=FileNotFoundError("git not found")),          patch('builtins.print') as mock_print:
        res = get_changed_files('C:\\dummy\\wt')
        assert res == []
        mock_print.assert_any_call("Error running git status in C:\\dummy\\wt: git not found")

def test_filter_and_copy_files_oserror():
    from scratch.copy_subagent_files import filter_and_copy_files
    changed_files = [('file1.py', ' M'), ('file2.py', ' M')]
    
    def mock_copy2(src, dst):
        if 'file1.py' in src:
            raise OSError("Copy failed")
        return None
        
    with patch('os.path.isdir', return_value=False),          patch('os.makedirs'),          patch('shutil.copy2', side_effect=mock_copy2) as mock_copy,          patch('builtins.print') as mock_print:
         
        filter_and_copy_files('C:\\src', changed_files, 'C:\\dst')
        
        # file1.pyのコピーが失敗しても、file2.pyのコピーが試みられるため、shutil.copy2は2回呼ばれる
        assert mock_copy.call_count == 2
        mock_print.assert_any_call("Error copying file1.py from C:\\src to C:\\dst: Copy failed")
