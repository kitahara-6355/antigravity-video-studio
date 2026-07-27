import os
import sys
import importlib
import pytest
from unittest.mock import patch, MagicMock

# sys.path にプロジェクトルートへのパスを追加する
# backend/tests から見ると、プロジェクトルートは2つ上。
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def test_remove_old_worktrees_success():
    """正常系テスト: 削除対象、カレントディレクトリ、セッションID保持対象が混在する場合"""
    worktree_list_output = (
        "C:/Users/PC_User/Desktop/script/video-automation [main-branch]\n"
        "\n"
        "C:/Users/PC_User/Desktop/script/video-automation_worktree_02e660a5-f119-464b-8073-81f4b664078b [session-branch]\n"
        "   \n"
        "C:/Users/PC_User/Desktop/script/video-automation_worktree_old [old-branch]\n"
    )
    
    mock_run_result = MagicMock()
    mock_run_result.stdout = worktree_list_output
    
    # subprocess.run と print をモックする
    with patch("subprocess.run") as mock_run, \
         patch("builtins.print") as mock_print:
        
        # 最初の run (list) は成功し、2回目の run (remove) も成功する
        mock_run.return_value = mock_run_result
        
        # モジュールを実行
        if "backend.scratch.remove_old_worktrees" in sys.modules:
            importlib.reload(sys.modules["backend.scratch.remove_old_worktrees"])
        else:
            importlib.import_module("backend.scratch.remove_old_worktrees")
        
        # 呼び出しを確認
        # 1回目は git worktree list
        # 2回目は git worktree remove --force C:/Users/PC_User/Desktop/script/video-automation_worktree_old
        assert mock_run.call_count == 2
        
        mock_run.assert_any_call(
            ["git", "worktree", "list"],
            capture_output=True, text=True,
            cwd="C:/Users/PC_User/Desktop/script/video-automation",
            check=True
        )
        
        mock_run.assert_any_call(
            ["git", "worktree", "remove", "--force", "C:/Users/PC_User/Desktop/script/video-automation_worktree_old"],
            cwd="C:/Users/PC_User/Desktop/script/video-automation",
            check=True
        )
        
        # printの出力を確認
        print_calls = [c[0][0] for c in mock_print.call_args_list]
        assert "Removing worktree: C:/Users/PC_User/Desktop/script/video-automation_worktree_old" in print_calls
        assert "Completed! Removed 1 worktrees." in print_calls


def test_remove_old_worktrees_list_failure():
    """異常系テスト: git worktree list コマンドが失敗した場合"""
    with patch("subprocess.run") as mock_run, \
         patch("builtins.print") as mock_print:
        
        # list取得で例外を発生させる
        mock_run.side_effect = Exception("git Command failed")
        
        # モジュールを実行
        if "backend.scratch.remove_old_worktrees" in sys.modules:
            importlib.reload(sys.modules["backend.scratch.remove_old_worktrees"])
        else:
            importlib.import_module("backend.scratch.remove_old_worktrees")
        
        # 1回しか呼ばれていないはず (list失敗で打ち切られるため)
        assert mock_run.call_count == 1
        
        print_calls = [c[0][0] for c in mock_print.call_args_list]
        assert "Error: git Command failed" in print_calls


def test_remove_old_worktrees_remove_failure():
    """異常系テスト: git worktree remove コマンドが一部失敗した場合"""
    worktree_list_output = (
        "C:/Users/PC_User/Desktop/script/video-automation_worktree_old1 [old1]\n"
        "C:/Users/PC_User/Desktop/script/video-automation_worktree_old2 [old2]\n"
    )
    
    mock_run_result = MagicMock()
    mock_run_result.stdout = worktree_list_output
    
    # 1回目の呼び出しでは list を返し、
    # 2回目 (old1削除) では例外を投げ、
    # 3回目 (old2削除) では正常終了する
    def mock_run_side_effect(cmd, *args, **kwargs):
        if "list" in cmd:
            return mock_run_result
        elif "old1" in cmd[4]:
            raise Exception("Access denied")
        else:
            return MagicMock()
            
    with patch("subprocess.run") as mock_run, \
         patch("builtins.print") as mock_print:
        
        mock_run.side_effect = mock_run_side_effect
        
        # モジュールを実行
        if "backend.scratch.remove_old_worktrees" in sys.modules:
            importlib.reload(sys.modules["backend.scratch.remove_old_worktrees"])
        else:
            importlib.import_module("backend.scratch.remove_old_worktrees")
        
        # list, remove (old1), remove (old2) の3回
        assert mock_run.call_count == 3
        
        print_calls = [c[0][0] for c in mock_print.call_args_list]
        assert "Failed to remove C:/Users/PC_User/Desktop/script/video-automation_worktree_old1: Access denied" in print_calls
        assert "Completed! Removed 1 worktrees." in print_calls
