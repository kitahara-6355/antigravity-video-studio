import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gemini_client_factory


@pytest.fixture(autouse=True)
def run_before_and_after_tests():
    # 各テストの前にシングルトン状態をリセット
    gemini_client_factory.reset_client()
    yield
    # 各テストの後にもリセット
    gemini_client_factory.reset_client()


def test_get_raw_client_no_api_key():
    """GOOGLE_API_KEY が設定されていない場合、None を返すこと"""
    with patch.dict(os.environ, {}, clear=True):
        assert gemini_client_factory._get_raw_client() is None


def test_get_raw_client_success():
    """GOOGLE_API_KEY が設定されている場合、genai.Client が正常に生成されること"""
    mock_client = MagicMock()
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-api-key"}):
        with patch("google.genai.Client", return_value=mock_client) as mock_init:
            client = gemini_client_factory._get_raw_client()
            assert client is mock_client
            mock_init.assert_called_once_with(api_key="test-api-key")


def test_get_raw_client_cached():
    """同じ API キーであれば、既存のクライアントがキャッシュから再利用されること"""
    mock_client = MagicMock()
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-api-key"}):
        with patch("google.genai.Client", return_value=mock_client) as mock_init:
            # 1回目の呼び出し
            client1 = gemini_client_factory._get_raw_client()
            # 2回目の呼び出し
            client2 = gemini_client_factory._get_raw_client()
            
            assert client1 is mock_client
            assert client2 is mock_client
            assert client1 is client2
            mock_init.assert_called_once()  # 初期化は1回のみ


def test_get_raw_client_key_changed():
    """API キーが変更された場合、新しいクライアントが再生成されること"""
    mock_client1 = MagicMock()
    mock_client2 = MagicMock()
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "key-1"}):
        with patch("google.genai.Client", return_value=mock_client1):
            client1 = gemini_client_factory._get_raw_client()
            assert client1 is mock_client1

    # キーを key-2 に変更
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "key-2"}):
        with patch("google.genai.Client", return_value=mock_client2) as mock_init2:
            client2 = gemini_client_factory._get_raw_client()
            assert client2 is mock_client2
            assert client1 is not client2
            mock_init2.assert_called_once_with(api_key="key-2")


def test_get_raw_client_exception():
    """クライアント初期化時に ValueError または ImportError が発生した場合、None を返し状態をクリアすること。
    それ以外の例外はそのままスローされること。
    """
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-api-key"}):
        # ValueError
        with patch("google.genai.Client", side_effect=ValueError("Invalid Key")):
            client = gemini_client_factory._get_raw_client()
            assert client is None
            assert gemini_client_factory._cached_raw_client is None
            assert gemini_client_factory._current_api_key is None

        # ImportError
        gemini_client_factory.reset_client()
        with patch("google.genai.Client", side_effect=ImportError("No module")):
            client = gemini_client_factory._get_raw_client()
            assert client is None
            assert gemini_client_factory._cached_raw_client is None
            assert gemini_client_factory._current_api_key is None

        # その他の Exception
        gemini_client_factory.reset_client()
        with patch("google.genai.Client", side_effect=Exception("Unexpected Error")):
            with pytest.raises(Exception, match="Unexpected Error"):
                gemini_client_factory._get_raw_client()


def test_get_gemini_client_no_raw():
    """生クライアントが None の場合、None を返すこと"""
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        assert gemini_client_factory.get_gemini_client() is None


def test_get_gemini_client_governed():
    """正常に GovernedModelsProxy でラップされたクライアントを返すこと"""
    mock_raw_client = MagicMock()
    mock_raw_client.models = MagicMock()
    mock_proxy = MagicMock()
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw_client):
        with patch("model_governance.GovernedModelsProxy", return_value=mock_proxy) as mock_proxy_init:
            client = gemini_client_factory.get_gemini_client()
            assert client is not None
            assert client._raw is mock_raw_client
            assert client.models is mock_proxy
            mock_proxy_init.assert_called_once_with(mock_raw_client.models, "gemini_client_factory")
            
            # 属性アクセスがフォールバックされることの確認
            mock_raw_client.some_attr = "value"
            assert client.some_attr == "value"


def test_get_gemini_client_cached():
    """同じ生クライアントの場合、キャッシュされた GovernedClient が返されること"""
    mock_raw_client = MagicMock()
    mock_raw_client.models = MagicMock()
    mock_proxy = MagicMock()
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw_client):
        with patch("model_governance.GovernedModelsProxy", return_value=mock_proxy):
            client1 = gemini_client_factory.get_gemini_client()
            client2 = gemini_client_factory.get_gemini_client()
            assert client1 is client2


def test_get_gemini_client_import_error():
    """model_governance が導入されていない場合、生クライアントをそのまま返すこと"""
    mock_raw_client = MagicMock()
    
    import sys
    # sys.modules から一時的に削除してインポートが走るように強制する
    had_module = "model_governance" in sys.modules
    old_module = sys.modules.pop("model_governance", None)
    
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "model_governance":
            raise ImportError("No module named 'model_governance'")
        return original_import(name, *args, **kwargs)
    
    try:
        with patch("gemini_client_factory._get_raw_client", return_value=mock_raw_client):
            with patch("builtins.__import__", side_effect=mock_import):
                client = gemini_client_factory.get_gemini_client()
                assert client is mock_raw_client
    finally:
        if had_module:
            sys.modules["model_governance"] = old_module


def test_reset_client():
    """reset_client が正しく状態をリセットすること"""
    gemini_client_factory._cached_raw_client = MagicMock()
    gemini_client_factory._current_api_key = "some-key"
    gemini_client_factory._cached_governed_client = MagicMock()
    
    gemini_client_factory.reset_client()
    
    assert gemini_client_factory._cached_raw_client is None
    assert gemini_client_factory._current_api_key is None
    assert gemini_client_factory._cached_governed_client is None


def test_get_raw_client_double_check_lock():
    """ダブルチェックロックが機能し、ロック取得後に既に初期化されていればそれを返すこと"""
    import threading
    mock_client = MagicMock()
    
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-api-key"}):
        with patch("google.genai.Client", return_value=mock_client) as mock_init:
            
            # _get_raw_client() のダブルチェックロック部分に入る前に、_clientが生成されたとみなすように
            # _lock をモックしてフックします。
            real_lock = gemini_client_factory._lock
            
            class HookedLock:
                def __enter__(self):
                    # ロック取得時点で、別のスレッドがすでに初期化したと仮定する
                    gemini_client_factory._cached_raw_client = mock_client
                    gemini_client_factory._current_api_key = "test-api-key"
                    return real_lock.__enter__()
                def __exit__(self, exc_type, exc_val, exc_tb):
                    return real_lock.__exit__(exc_type, exc_val, exc_tb)
            
            with patch("gemini_client_factory._lock", HookedLock()):
                client = gemini_client_factory._get_raw_client()
                assert client is mock_client
                # すでに初期化されているので、genai.Clientの新規生成は呼ばれないはず
                mock_init.assert_not_called()



def test_get_gemini_client_double_check_lock():
    """get_gemini_client のダブルチェックロックが機能し、ロック取得後に既に初期化されていればそれを返すこと"""
    mock_raw_client = MagicMock()
    mock_raw_client.models = MagicMock()
    mock_proxy = MagicMock()
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw_client):
        with patch("model_governance.GovernedModelsProxy", return_value=mock_proxy):
            real_lock = gemini_client_factory._lock
            mock_governed_client = gemini_client_factory.GovernedClient(mock_raw_client)
            
            class HookedLock:
                def __enter__(self):
                    gemini_client_factory._cached_governed_client = mock_governed_client
                    return real_lock.__enter__()
                def __exit__(self, exc_type, exc_val, exc_tb):
                    return real_lock.__exit__(exc_type, exc_val, exc_tb)
            
            with patch("gemini_client_factory._lock", HookedLock()):
                gemini_client_factory._cached_governed_client = None
                client = gemini_client_factory.get_gemini_client()
                assert client is mock_governed_client
