import sys
import os
from unittest.mock import patch, mock_open
import pytest

# テスト対象モジュールのインポート関数
def import_scan_existing():
    # キャッシュをクリアして再実行を保証
    if "backend.tests.scratch.scan_existing" in sys.modules:
        del sys.modules["backend.tests.scratch.scan_existing"]
    # backend.tests.scratch.scan_existing をインポートして実行
    import backend.tests.scratch.scan_existing as m
    m.run_scan()
    return m

def test_scan_existing_success():
    """正常系のテスト。
    E2Eテストファイルからクラスが正常に抽出され、未抽出クラスが特定されることを検証する。
    """
    mock_files = ["test_e2e_m36_login.py", "test_e2e_m36_signup.py"]
    
    # open のモックで、ファイルごとに異なる内容を返す
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "class TestE2E1Login:\n    pass\nclass TestE2E2Login:\n    pass"
        elif "test_e2e_m36_signup.py" in path_str:
            content = "class TestE2E3Signup:\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2E1Login:\n    pass\nclass TestE2E2Login:\n    pass\nclass TestE2E3Signup:\n    pass\nclass TestE2E4Missing:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        # print の呼び出しから期待する出力が含まれているか検証
        printed_args = []
        for call in mock_print.call_args_list:
            if call[0]:
                printed_args.append(str(call[0][0]))
        
        # 抽出されたクラスの表示
        assert any("test_e2e_m36_login.py:" in arg for arg in printed_args)
        assert any("  - TestE2E1Login" in arg for arg in printed_args)
        assert any("  - TestE2E2Login" in arg for arg in printed_args)
        assert any("test_e2e_m36_signup.py:" in arg for arg in printed_args)
        assert any("  - TestE2E3Signup" in arg for arg in printed_args)
        
        # 未抽出クラスの表示
        assert any("--- NOT EXTRACTED CLASSES ---" in arg for arg in printed_args)
        assert any("  - TestE2E4Missing" in arg for arg in printed_args)
        
        # 抽出済みのクラスは未抽出リストに含まれないこと
        not_extracted_start = False
        not_extracted_list = []
        for arg in printed_args:
            if "--- NOT EXTRACTED CLASSES ---" in arg:
                not_extracted_start = True
                continue
            if not_extracted_start:
                not_extracted_list.append(arg)
                
        assert not any("TestE2E1Login" in arg for arg in not_extracted_list)
        assert not any("TestE2E2Login" in arg for arg in not_extracted_list)
        assert not any("TestE2E3Signup" in arg for arg in not_extracted_list)

def test_scan_existing_dir_not_found():
    """ディレクトリが存在しない場合の例外境界テスト。
    """
    with patch("os.listdir") as mock_listdir:
        mock_listdir.side_effect = FileNotFoundError("Directory not found")
        
        with pytest.raises(FileNotFoundError):
            import_scan_existing()

def test_scan_existing_file_read_error():
    """ファイル読み込みエラー時の例外境界テスト。
    """
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            raise PermissionError("Permission denied")
        elif "test_e2e_browser_m36.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        with pytest.raises(PermissionError):
            import_scan_existing()

def test_scan_existing_orig_file_not_found():
    """オリジナルファイルが存在しない場合の例外境界テスト。
    """
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        elif "test_e2e_browser_m36.py" in path_str:
            raise FileNotFoundError("Original file not found")
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        with pytest.raises(FileNotFoundError):
            import_scan_existing()


def test_scan_existing_no_target_files():
    """対象ファイルが一切存在しない場合のテスト。
    """
    mock_files = []
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_browser_m36.py" in path_str:
            return mock_open(read_data="class TestE2E1Missing:\n    pass").return_value
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        
        # NOT EXTRACTED CLASSES に TestE2E1Missing が表示されること
        assert any("--- NOT EXTRACTED CLASSES ---" in arg for arg in printed_args)
        assert any("  - TestE2E1Missing" in arg for arg in printed_args)

def test_scan_existing_non_matching_classes():
    """TestE2Eプレフィックスを持たないクラス定義が存在する場合のテスト。
    """
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "class TestE2E1Login:\n    pass\nclass HelperClass:\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2E1Login:\n    pass\nclass HelperClass:\n    pass\nclass TestE2EMissing:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        
        # TestE2E1Login は抽出されるが HelperClass は抽出されないこと
        assert any("  - TestE2E1Login" in arg for arg in printed_args)
        assert not any("HelperClass" in arg for arg in printed_args)
        assert any("  - TestE2EMissing" in arg for arg in printed_args)

def test_scan_existing_ignored_files():
    """プレフィックスや拡張子が異なるファイルが無視されることを検証するテスト。
    """
    # プレフィックスが違う、または拡張子が違うファイルを混ぜる
    mock_files = [
        "test_e2e_m36_login.py", 
        "test_helper.py", 
        "test_e2e_m36_data.json"
    ]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "class TestE2E1Login:\n    pass"
        elif "test_helper.py" in path_str:
            content = "class TestE2EHelper:\n    pass"
        elif "test_e2e_m36_data.json" in path_str:
            content = "class TestE2EJson:\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2E1Login:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        
        # test_e2e_m36_login.py のクラスは表示されるが、他は無視されること
        assert any("test_e2e_m36_login.py:" in arg for arg in printed_args)
        assert not any("test_helper.py:" in arg for arg in printed_args)
        assert not any("test_e2e_m36_data.json:" in arg for arg in printed_args)
        assert not any("TestE2EHelper" in arg for arg in printed_args)
        assert not any("TestE2EJson" in arg for arg in printed_args)


def test_scan_existing_line_endings():
    """Windows形式の改行コード(CRLF)でもクラス名が正常に抽出されることを検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "class TestE2E1Login:\r\n    pass\r\nclass TestE2E2Login:\r\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2E1Login:\r\n    pass\r\nclass TestE2E2Login:\r\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("  - TestE2E1Login" in arg for arg in printed_args)
        assert any("  - TestE2E2Login" in arg for arg in printed_args)


def test_scan_existing_utf8_encoding():
    """UTF-8マルチバイト文字（日本語コメントなど）が含まれていても正常に読み込めることを検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "# 日本語のコメントです\nclass TestE2E1Login:\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2E1Login:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        assert any("  - TestE2E1Login" in arg for arg in printed_args)


def test_scan_existing_sorting_logic():
    """抽出されたクラスがアルファベット順にソートされて出力されることを厳密に検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = "class TestE2EZ:\n    pass\nclass TestE2EB:\n    pass\nclass TestE2EA:\n    pass"
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2EA:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        
        idx_a = next(i for i, arg in enumerate(printed_args) if "TestE2EA" in arg)
        idx_b = next(i for i, arg in enumerate(printed_args) if "TestE2EB" in arg)
        idx_z = next(i for i, arg in enumerate(printed_args) if "TestE2EZ" in arg)
        
        assert idx_a < idx_b < idx_z


def test_scan_existing_class_patterns():
    """様々なクラス定義表記の抽出挙動を検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            content = (
                "class TestE2EWithInheritance(unittest.TestCase):\n"
                "    pass\n"
                "class TestE2EWithSpaces   :\n"
                "    pass\n"
                "class NotE2EClass:\n"
                "    pass\n"
                "  class TestE2EIndented:\n"
                "    pass\n"
            )
        elif "test_e2e_browser_m36.py" in path_str:
            content = "class TestE2EWithInheritance:\n    pass"
        else:
            content = ""
        return mock_open(read_data=content).return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("builtins.print") as mock_print:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        m = import_scan_existing()
        
        printed_args = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
        
        assert any("  - TestE2EWithInheritance" in arg for arg in printed_args)
        assert any("  - TestE2EWithSpaces" in arg for arg in printed_args)
        assert not any("NotE2EClass" in arg for arg in printed_args)
        assert not any("TestE2EIndented" in arg for arg in printed_args)


def test_scan_existing_dir_not_found_logs_error():
    """ディレクトリが存在しない場合に、エラーログが出力され例外が再スローされることを検証。"""
    with patch("os.listdir") as mock_listdir, \
         patch("sys.stderr.write") as mock_stderr_write:
        mock_listdir.side_effect = FileNotFoundError("Directory not found")
        
        with pytest.raises(FileNotFoundError):
            import_scan_existing()
        
        # sys.stderr.write が呼ばれ、エラーメッセージが含まれていることを確認
        assert mock_stderr_write.called
        stderr_output = "".join(call[0][0] for call in mock_stderr_write.call_args_list)
        assert "Failed to list directory" in stderr_output

def test_scan_existing_file_read_error_logs_error():
    """ファイル読み込み時にエラーが発生した場合に、エラーログが出力され例外が再スローされることを検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            raise PermissionError("Permission denied")
        elif "test_e2e_browser_m36.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("sys.stderr.write") as mock_stderr_write:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        with pytest.raises(PermissionError):
            import_scan_existing()
            
        assert mock_stderr_write.called
        stderr_output = "".join(call[0][0] for call in mock_stderr_write.call_args_list)
        assert "Failed to read file" in stderr_output

def test_scan_existing_orig_file_not_found_logs_error():
    """オリジナルファイルが存在しない場合に、エラーログが出力され例外が再スローされることを検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        elif "test_e2e_browser_m36.py" in path_str:
            raise FileNotFoundError("Original file not found")
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("sys.stderr.write") as mock_stderr_write:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        with pytest.raises(FileNotFoundError):
            import_scan_existing()
            
        assert mock_stderr_write.called
        stderr_output = "".join(call[0][0] for call in mock_stderr_write.call_args_list)
        assert "Failed to read original file" in stderr_output



def test_scan_existing_file_unicode_decode_error():
    """ファイル読み込み時にデコードエラーが発生した場合の例外境界テスト。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            mock = mock_open().return_value
            mock.read.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return mock
        elif "test_e2e_browser_m36.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func:
         
         mock_listdir.return_value = mock_files
         mock_open_func.side_effect = open_side_effect
         
         with pytest.raises(UnicodeDecodeError):
             import_scan_existing()

def test_scan_existing_file_unicode_decode_error_logs_error():
    """ファイル読み込み時にデコードエラーが発生した場合に、エラーログが出力され例外が再スローされることを検証。"""
    mock_files = ["test_e2e_m36_login.py"]
    
    def open_side_effect(path, *args, **kwargs):
        path_str = str(path)
        if "test_e2e_m36_login.py" in path_str:
            mock = mock_open().return_value
            mock.read.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
            return mock
        elif "test_e2e_browser_m36.py" in path_str:
            return mock_open(read_data="class TestE2E1:\n    pass").return_value
        return mock_open(read_data="").return_value

    with patch("os.listdir") as mock_listdir, \
         patch("builtins.open") as mock_open_func, \
         patch("sys.stderr.write") as mock_stderr_write:
         
        mock_listdir.return_value = mock_files
        mock_open_func.side_effect = open_side_effect
        
        with pytest.raises(UnicodeDecodeError):
            import_scan_existing()
            
        assert mock_stderr_write.called
        stderr_output = "".join(call[0][0] for call in mock_stderr_write.call_args_list)
        assert "Failed to read file" in stderr_output
