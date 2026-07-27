import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from google.genai.errors import APIError

# backend へのパスを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from list_models import list_gemini_models
import gemini_client_factory

@pytest.fixture(autouse=True)
def run_before_and_after_tests():
    # テスト前後の状態リセット
    gemini_client_factory.reset_client()
    yield
    gemini_client_factory.reset_client()

def test_list_gemini_models_no_api_key():
    """GOOGLE_API_KEY がない場合、空のリストを返すこと"""
    with patch.dict(os.environ, {}, clear=True):
        models = list_gemini_models()
        assert models == []

def test_list_gemini_models_client_none():
    """get_gemini_client() が None を返した場合、AttributeError を起こさずに空のリストを返すこと"""
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=None):
            models = list_gemini_models()
            assert models == []

def test_list_gemini_models_api_exception():
    """client.models.list() 呼び出し時に例外が発生した場合、例外をキャッチして空のリストを返すこと"""
    mock_client = MagicMock()
    mock_client.models.list.side_effect = APIError(500, {"message": "API error"})
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            models = list_gemini_models()
            assert models == []

def test_list_gemini_models_success():
    """正常系で、models から名前を取得してリストで返すこと"""
    mock_client = MagicMock()
    
    # name 属性を持つダミーのモデルオブジェクト
    model_a = MagicMock()
    model_a.name = "gemini-1.5-pro"
    model_b = MagicMock()
    model_b.name = "gemini-1.5-flash"
    
    mock_client.models.list.return_value = [model_a, model_b]
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            models = list_gemini_models()
            assert models == ["gemini-1.5-pro", "gemini-1.5-flash"]

def test_list_gemini_models_empty_or_invalid_items():
    """戻り値が None、または name 属性がない無効なオブジェクトが含まれる場合に正しく動作すること"""
    mock_client = MagicMock()
    
    # 正常なものと、name 属性のないもの、None が混在しているリスト
    model_a = MagicMock()
    model_a.name = "gemini-1.5-pro"
    
    model_invalid = MagicMock(spec=[]) # name 属性を持たない
    
    mock_client.models.list.return_value = [model_a, model_invalid, None]
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            models = list_gemini_models()
            assert models == ["gemini-1.5-pro"]


def test_list_models_main_block():
    """__main__ ブロックが正常に実行され、モデル一覧を出力すること"""
    import runpy
    from unittest.mock import patch, MagicMock
    mock_client = MagicMock()
    model_a = MagicMock()
    model_a.name = "gemini-1.5-pro"
    mock_client.models.list.return_value = [model_a]
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            with patch("builtins.print") as mock_print:
                runpy.run_module("list_models", run_name="__main__")
                mock_print.assert_any_call("--- Available Models ---")
                mock_print.assert_any_call("Model: gemini-1.5-pro")


def test_list_gemini_models_empty_api_key():
    """GOOGLE_API_KEY が空文字列の場合、空のリストを返すこと"""
    with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}):
        models = list_gemini_models()
        assert models == []


def test_list_gemini_models_empty_list():
    """client.models.list() が空リストを返した場合、空リストを返すこと"""
    mock_client = MagicMock()
    mock_client.models.list.return_value = []
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            models = list_gemini_models()
            assert models == []


def test_list_gemini_models_falsy_names():
    """name 属性の値が空文字列や None などの Falsy な値の場合、スキップすること"""
    mock_client = MagicMock()
    
    model_valid = MagicMock()
    model_valid.name = "gemini-1.5-pro"
    
    model_empty_name = MagicMock()
    model_empty_name.name = ""
    
    model_none_name = MagicMock()
    model_none_name.name = None
    
    mock_client.models.list.return_value = [model_valid, model_empty_name, model_none_name]
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            models = list_gemini_models()
            assert models == ["gemini-1.5-pro"]


def test_list_gemini_models_unexpected_exception():
    """client.models.list() が APIError 以外の一般例外を発生させた場合、呼び出し元に伝播すること"""
    mock_client = MagicMock()
    mock_client.models.list.side_effect = RuntimeError("unexpected error")
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="unexpected error"):
                list_gemini_models()

