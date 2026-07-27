import sys
from unittest.mock import patch, MagicMock
import pytest

def test_check_app_success_mocked(capsys):
    # main モジュールのインポートでダミーの app を返すようにモック化する
    mock_app = MagicMock()
    mock_route = MagicMock()
    mock_route.path = "/test"
    mock_route.name = "test_route"
    mock_app.routes = [mock_route]
    
    mock_main = MagicMock()
    mock_main.app = mock_app
    
    # sys.modules をモック化し、backend.check_app を削除してリロードさせる
    with patch.dict(sys.modules, {"main": mock_main}):
        if "backend.check_app" in sys.modules:
            del sys.modules["backend.check_app"]
        
        import backend.check_app
        
        captured = capsys.readouterr()
        assert "Importing main..." in captured.out
        assert "ROUTES FOUND: 1" in captured.out
        assert "/test [test_route]" in captured.out

def test_check_app_exception_mocked(capsys):
    # builtins.__import__ をモック化して main のインポート時に例外を投げる
    import builtins
    original_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == "main":
            raise ImportError("Mocked import error")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        with patch.dict(sys.modules):
            if "main" in sys.modules:
                del sys.modules["main"]
            if "backend.check_app" in sys.modules:
                del sys.modules["backend.check_app"]
                
            import backend.check_app
            
            captured = capsys.readouterr()
            assert "Importing main..." in captured.out
            assert "ImportError: Failed to import 'main' or its dependencies: Mocked import error" in captured.err
            assert "Traceback" in captured.err


def test_check_app_attribute_error_mocked(capsys):
    # main モジュールのインポートは成功するが app 属性がない場合をシミュレート
    mock_main = MagicMock(spec=[])  # app 属性を持たない
    
    with patch.dict(sys.modules, {"main": mock_main}):
        if "backend.check_app" in sys.modules:
            del sys.modules["backend.check_app"]
        
        import backend.check_app
        
        captured = capsys.readouterr()
        assert "Importing main..." in captured.out
        assert "ImportError: Failed to import 'main' or its dependencies: cannot import name 'app'" in captured.err
        assert "Traceback" in captured.err

def test_check_app_empty_routes_mocked(capsys):
    # app.routes が空リストの場合
    mock_app = MagicMock()
    mock_app.routes = []
    mock_main = MagicMock()
    mock_main.app = mock_app
    
    with patch.dict(sys.modules, {"main": mock_main}):
        if "backend.check_app" in sys.modules:
            del sys.modules["backend.check_app"]
        
        import backend.check_app
        
        captured = capsys.readouterr()
        assert "Importing main..." in captured.out
        assert "ROUTES FOUND: 0" in captured.out

def test_check_app_subprocess_execution():
    import subprocess
    import os
    # 実際に python コマンドで実行
    result = subprocess.run(
        [sys.executable, "backend/check_app.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "."}
    )
    # 実行できることを検証。正常終了するか、もしくは main インポートエラー（データベース未設定等）のいずれであっても、
    # スクリプト自体が syntax error や例外で異常終了せず、エラーメッセージが適切に出力されることを確認。
    # 戻り値は 0 のはず（try-except で囲まれており、例外が起きても終了コードは 0 になる設計であるため）
    assert result.returncode == 0
    assert "Importing main..." in result.stdout
    # main のインポート結果に応じて、どちらか一方が出力されているはず
    assert ("ROUTES FOUND" in result.stdout or "Error importing main" in result.stdout)
