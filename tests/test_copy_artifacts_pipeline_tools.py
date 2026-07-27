import sys
import pytest
from unittest.mock import patch, MagicMock
from backend.agents.orchestration.copy_artifacts_pipeline_tools import copy_artifacts_pipeline_tools

def test_copy_artifacts_pipeline_tools_success():
    """すべてのソースファイルが存在する場合に、正しくコピー処理が実行されることを検証します。"""
    with patch("os.path.exists", return_value=True) as mock_exists, \
         patch("shutil.copy2") as mock_copy, \
         patch("os.makedirs") as mock_makedirs, \
         patch("builtins.print") as mock_print:
        
        res = copy_artifacts_pipeline_tools()
        
        assert res is True
        assert mock_exists.call_count == 3
        assert mock_copy.call_count == 3
        assert mock_makedirs.call_count == 3
        mock_print.assert_any_call("PIPELINE_TOOLS_COPY_COMPLETED")


def test_copy_artifacts_pipeline_tools_missing_files():
    """ソースファイルが存在しない場合に、コピーをスキップして警告を表示することを検証します。"""
    with patch("os.path.exists", return_value=False) as mock_exists, \
         patch("shutil.copy2") as mock_copy, \
         patch("os.makedirs") as mock_makedirs, \
         patch("builtins.print") as mock_print:
        
        res = copy_artifacts_pipeline_tools()
        
        assert res is False
        assert mock_exists.call_count == 3
        mock_copy.assert_not_called()
        mock_makedirs.assert_not_called()


def test_copy_artifacts_pipeline_tools_permission_error():
    """パーミッションエラーが発生した場合に、警告を出力して失敗ステータスを返すことを検証します。"""
    with patch("os.path.exists", return_value=True), \
         patch("shutil.copy2", side_effect=PermissionError("Permission denied")), \
         patch("os.makedirs"), \
         patch("builtins.print") as mock_print:
        
        res = copy_artifacts_pipeline_tools()
        assert res is False


def test_copy_artifacts_pipeline_tools_file_not_found_error():
    """FileNotFoundErrorが発生した場合に、警告を出力して失敗ステータスを返すことを検証します。"""
    with patch("os.path.exists", return_value=True), \
         patch("shutil.copy2", side_effect=FileNotFoundError("File not found")), \
         patch("os.makedirs"), \
         patch("builtins.print") as mock_print:
        
        res = copy_artifacts_pipeline_tools()
        assert res is False


def test_copy_artifacts_pipeline_tools_general_exception():
    """予期せぬ一般例外が発生した場合に、警告を出力して失敗ステータスを返すことを検証します。"""
    with patch("os.path.exists", return_value=True), \
         patch("shutil.copy2", side_effect=ValueError("Unexpected error")), \
         patch("os.makedirs"), \
         patch("builtins.print") as mock_print:
        
        res = copy_artifacts_pipeline_tools()
        assert res is False


def test_copy_artifacts_pipeline_tools_dest_base_resolution_error():
    """__file__からプロジェクトルートを解決する際に例外が発生した場合、フォールバックパスが使用されることを検証します。"""
    # __file__ が存在しないなどの極端な状況をシミュレートするため、os.path.abspath 等で例外をスローさせる
    with patch("os.path.exists", return_value=False), \
         patch("os.path.abspath", side_effect=Exception("Simulated path resolution error")), \
         patch("builtins.print"):
        
        # 例外が発生しても dest_base はフォールバックされ、正常に関数が終了すること
        res = copy_artifacts_pipeline_tools()
        assert res is False

