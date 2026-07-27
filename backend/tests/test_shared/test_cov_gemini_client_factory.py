import os
import sys
from unittest.mock import patch, MagicMock
import pytest

import gemini_client_factory
from gemini_client_factory import (
    get_gemini_client,
    _get_raw_client,
    reset_client
)

@pytest.fixture(autouse=True)
def setup_teardown():
    reset_client()
    yield
    reset_client()

def test_reset_client():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client") as mock_client:
            _get_raw_client()
            assert gemini_client_factory._cached_raw_client is not None
            assert gemini_client_factory._current_api_key == "test-key"
            
            get_gemini_client()
            assert gemini_client_factory._cached_governed_client is not None
 
    reset_client()
    assert gemini_client_factory._cached_raw_client is None
    assert gemini_client_factory._current_api_key is None
    assert gemini_client_factory._cached_governed_client is None

def test_get_raw_client_no_api_key():
    with patch.dict(os.environ, {}, clear=True):
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        raw = _get_raw_client()
        assert raw is None

def test_get_raw_client_success():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value = mock_instance
            
            raw = _get_raw_client()
            assert raw is mock_instance
            mock_client_class.assert_called_once_with(api_key="test-key")
            
            # キャッシュヒット
            raw2 = _get_raw_client()
            assert raw2 is mock_instance
            assert mock_client_class.call_count == 1

def test_get_raw_client_api_key_change():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "key-1"}):
        with patch("google.genai.Client") as mock_client_class:
            mock_instance1 = MagicMock()
            mock_client_class.return_value = mock_instance1
            
            raw1 = _get_raw_client()
            assert raw1 is mock_instance1
            
    # キー変更時
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "key-2"}):
        with patch("google.genai.Client") as mock_client_class:
            mock_instance2 = MagicMock()
            mock_client_class.return_value = mock_instance2
            
            raw2 = _get_raw_client()
            assert raw2 is mock_instance2
            mock_client_class.assert_called_once_with(api_key="key-2")

def test_get_raw_client_import_error():
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "google" or name.startswith("google."):
            raise ImportError("Mocked import error for google")
        return original_import(name, *args, **kwargs)

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("builtins.__import__", side_effect=mock_import):
            raw = _get_raw_client()
            assert raw is None

def test_get_raw_client_value_error():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client", side_effect=ValueError("Invalid key format")):
            raw = _get_raw_client()
            assert raw is None

def test_get_raw_client_generic_exception():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client", side_effect=Exception("Connection refused")):
            with pytest.raises(Exception, match="Connection refused"):
                _get_raw_client()

def test_get_gemini_client_raw_is_none():
    with patch.dict(os.environ, {}, clear=True):
        if "GOOGLE_API_KEY" in os.environ:
            del os.environ["GOOGLE_API_KEY"]
        client = get_gemini_client()
        assert client is None

def test_get_gemini_client_governed_success():
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value = mock_instance
            
            mock_proxy = MagicMock()
            with patch("model_governance.GovernedModelsProxy", return_value=mock_proxy) as mock_proxy_class:
                client = get_gemini_client()
                assert client is not None
                assert client._raw is mock_instance
                assert client.models is mock_proxy
                mock_proxy_class.assert_called_once_with(mock_instance.models, "gemini_client_factory")
                
                # キャッシュ動作確認
                client2 = get_gemini_client()
                assert client2 is client
                
                # Attribute access 委譲確認 (__getattr__)
                mock_instance.some_method = MagicMock(return_value="hello")
                assert client.some_method() == "hello"
                mock_instance.some_method.assert_called_once()

def test_get_gemini_client_model_governance_import_error():
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "model_governance":
            raise ImportError("Mocked import error for model_governance")
        return original_import(name, *args, **kwargs)

    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
        with patch("google.genai.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value = mock_instance
            
            with patch("builtins.__import__", side_effect=mock_import):
                client = get_gemini_client()
                assert client is mock_instance

def test_double_check_lock():
    import threading
    real_lock = threading.Lock()
    
    class MockLock:
        def __enter__(self):
            real_lock.__enter__()
            gemini_client_factory._cached_raw_client = "some-client"
            gemini_client_factory._current_api_key = "test-key"
            return self
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            return real_lock.__exit__(exc_type, exc_val, exc_tb)
            
    mock_lock = MockLock()
    original_lock = gemini_client_factory._lock
    gemini_client_factory._lock = mock_lock
    try:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            gemini_client_factory._cached_raw_client = None
            gemini_client_factory._current_api_key = None
            
            raw = _get_raw_client()
            assert raw == "some-client"
    finally:
        gemini_client_factory._lock = original_lock
