import os
import sys
import logging
import threading
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# テスト対象のモジュールをインポートするためにパスを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from gemini_client_factory import (
    GovernedAioProxy,
    GovernedClient,
    get_gemini_client,
    reset_client,
    _get_api_key,
    _create_raw_client,
    _is_raw_client_valid,
    _get_raw_client,
    _is_governed_client_valid,
    _create_governed_client_safely
)

@pytest.fixture(autouse=True)
def clean_factory_state():
    """テストごとにファクトリのグローバルキャッシュをリセットする"""
    reset_client()
    yield
    reset_client()

def test_governed_aio_proxy_basics():
    """GovernedAioProxy が正しく models をラップし、その他の属性を raw_aio にフォールバックすること"""
    mock_raw_aio = MagicMock()
    mock_raw_aio.models = MagicMock()
    mock_raw_aio.some_other_method = MagicMock(return_value="hello")

    proxy = GovernedAioProxy(mock_raw_aio)
    
    # models が GovernedAsyncModelsProxy でラップされていることを確認
    from model_governance import GovernedAsyncModelsProxy
    assert isinstance(proxy.models, GovernedAsyncModelsProxy)
    
    # __getattr__ によるフォールバック動作
    assert proxy.some_other_method() == "hello"
    mock_raw_aio.some_other_method.assert_called_once()

def test_governed_client_basics():
    """GovernedClient が models, aio を適切にラップし、他の属性を生クライアントにフォールバックすること"""
    mock_raw_client = MagicMock()
    mock_raw_client.models = MagicMock()
    mock_raw_client.some_client_method = MagicMock(return_value="world")

    # シナリオ1: aio が存在する場合
    mock_raw_client.aio = MagicMock()
    mock_raw_client.aio.models = MagicMock()
    
    client_with_aio = GovernedClient(mock_raw_client)
    from model_governance import GovernedModelsProxy
    assert isinstance(client_with_aio.models, GovernedModelsProxy)
    assert isinstance(client_with_aio.aio, GovernedAioProxy)
    assert client_with_aio.some_client_method() == "world"

    # シナリオ2: aio が存在しない場合
    mock_raw_client_no_aio = MagicMock(spec=["models", "some_client_method"])
    mock_raw_client_no_aio.models = MagicMock()
    mock_raw_client_no_aio.some_client_method = MagicMock(return_value="no_aio")
    
    client_no_aio = GovernedClient(mock_raw_client_no_aio)
    assert not hasattr(client_no_aio, "aio")
    assert client_no_aio.some_client_method() == "no_aio"

def test_get_api_key(monkeypatch):
    """_get_api_key が環境変数 GOOGLE_API_KEY を正しく取得すること"""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-api-key")
    assert _get_api_key() == "test-api-key"

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert _get_api_key() is None

def test_create_raw_client():
    """_create_raw_client が google.genai.Client を呼び出すこと"""
    with patch("google.genai.Client") as mock_genai_client:
        _create_raw_client("dummy-key")
        mock_genai_client.assert_called_once_with(api_key="dummy-key")

def test_is_raw_client_valid():
    """_is_raw_client_valid の有効性検証ロジック"""
    mock_client = MagicMock()
    assert _is_raw_client_valid(mock_client, "keyA", "keyA") is True
    assert _is_raw_client_valid(None, "keyA", "keyA") is False
    assert _is_raw_client_valid(mock_client, "keyA", "keyB") is False

def test_get_raw_client_no_key(monkeypatch):
    """API キーがない場合、_get_raw_client は None を返すこと"""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert _get_raw_client() is None

def test_get_raw_client_cached_and_rotation(monkeypatch):
    """_get_raw_client のキャッシュとキーローテーション"""
    monkeypatch.setenv("GOOGLE_API_KEY", "key-1")
    
    mock_client_1 = MagicMock()
    mock_client_2 = MagicMock()
    
    with patch("gemini_client_factory._create_raw_client", side_effect=[mock_client_1, mock_client_2]) as mock_create:
        # 初回取得: 新規作成される
        clientA = _get_raw_client()
        assert clientA is mock_client_1
        mock_create.assert_called_once_with("key-1")
        
        # 2回目取得: キャッシュが使われる
        clientB = _get_raw_client()
        assert clientB is mock_client_1
        assert mock_create.call_count == 1
        
        # APIキー変更
        monkeypatch.setenv("GOOGLE_API_KEY", "key-2")
        clientC = _get_raw_client()
        assert clientC is mock_client_2
        assert mock_create.call_count == 2
        mock_create.assert_any_call("key-2")

def test_get_raw_client_creation_failures(monkeypatch):
    """_create_raw_client での ImportError や ValueError 発生時に None を返すこと"""
    monkeypatch.setenv("GOOGLE_API_KEY", "valid-key")
    
    with patch("gemini_client_factory._create_raw_client", side_effect=ImportError("mock import error")):
        assert _get_raw_client() is None

    with patch("gemini_client_factory._create_raw_client", side_effect=ValueError("mock value error")):
        assert _get_raw_client() is None

def test_get_raw_client_thread_safety(monkeypatch):
    """マルチスレッド環境下で _get_raw_client がスレッドセーフに動作すること"""
    monkeypatch.setenv("GOOGLE_API_KEY", "thread-key")
    
    mock_client = MagicMock()
    created_count = 0
    lock = threading.Lock()
    
    def mock_create(api_key):
        nonlocal created_count
        with lock:
            created_count += 1
        # スレッドの競合を誘発させるための微小なスリープ
        import time
        time.sleep(0.01)
        return mock_client

    with patch("gemini_client_factory._create_raw_client", side_effect=mock_create):
        threads = []
        results = []
        
        def worker():
            client = _get_raw_client()
            results.append(client)
            
        for _ in range(10):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        assert len(results) == 10
        for r in results:
            assert r is mock_client
        assert created_count == 1

def test_is_governed_client_valid():
    """_is_governed_client_valid の検証"""
    mock_raw = MagicMock()
    mock_gov = MagicMock()
    mock_gov._raw = mock_raw
    
    assert _is_governed_client_valid(mock_gov, mock_raw) is True
    assert _is_governed_client_valid(None, mock_raw) is False
    assert _is_governed_client_valid(mock_gov, MagicMock()) is False

def test_create_governed_client_safely_success():
    """_create_governed_client_safely が正常に GovernedClient を返すこと"""
    mock_raw = MagicMock()
    mock_raw.models = MagicMock()
    with patch("gemini_client_factory.GovernedClient", return_value="wrapped_client") as mock_class:
        res = _create_governed_client_safely(mock_raw)
        assert res == "wrapped_client"
        mock_class.assert_called_once_with(mock_raw)

def test_create_governed_client_safely_import_error():
    """ImportError が発生した場合、警告ログを出して生クライアントを返すこと"""
    mock_raw = MagicMock()
    with patch("gemini_client_factory.GovernedClient", side_effect=ImportError("no model_governance")):
        res = _create_governed_client_safely(mock_raw)
        assert res is mock_raw

def test_create_governed_client_safely_general_exception():
    """一般的な例外が発生した場合、技術負債を登録し、生クライアントを返すこと"""
    mock_raw = MagicMock()
    mock_td_store = MagicMock()
    
    # model_governance 適用時に一般的な例外を発生させる
    with patch("gemini_client_factory.GovernedClient", side_effect=Exception("Governed client creation failed")), \
         patch("agents.memory.technical_debt.technical_debt_store", mock_td_store):
         
        res = _create_governed_client_safely(mock_raw)
        assert res is mock_raw
        mock_td_store.register_debt.assert_called_once()
        # 引数の確認
        kwargs = mock_td_store.register_debt.call_args[1]
        assert kwargs["category"] == "ACCEPTED_SAFETY"
        assert kwargs["file_path"] == "backend/gemini_client_factory.py"
        assert "Governed client creation failed" in kwargs["notes"]

def test_create_governed_client_safely_td_error():
    """技術負債の登録自体が失敗（例外発生）した場合でも、安全に生クライアントを返すこと"""
    mock_raw = MagicMock()
    
    # インポート時に ImportError を投げさせる
    real_import = __import__
    def mock_import(name, *args, **kwargs):
        if "technical_debt" in name:
            raise ImportError("mock import error")
        return real_import(name, *args, **kwargs)
    
    with patch("gemini_client_factory.GovernedClient", side_effect=Exception("Governed client creation failed")), \
         patch("builtins.__import__", side_effect=mock_import):
        res = _create_governed_client_safely(mock_raw)
        assert res is mock_raw

def test_get_gemini_client_double_check_lock(monkeypatch):
    """複数スレッドからの get_gemini_client 同時呼び出しでダブルチェックロックが機能すること"""
    monkeypatch.setenv("GOOGLE_API_KEY", "thread-key-double-check")
    
    mock_raw = MagicMock()
    mock_raw.models = MagicMock()
    mock_gov = MagicMock(spec=GovernedClient)
    mock_gov._raw = mock_raw
    
    lock = threading.Lock()
    created_count = 0
    
    def mock_create_governed(raw):
        nonlocal created_count
        with lock:
            created_count += 1
        # 他のスレッドがロックの獲得待ちになるようにスリープを挟む
        import time
        time.sleep(0.05)
        return mock_gov

    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw), \
         patch("gemini_client_factory._create_governed_client_safely", side_effect=mock_create_governed):
         
        threads = []
        results = []
        
        def worker():
            client = get_gemini_client()
            results.append(client)
            
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        assert len(results) == 5
        for r in results:
            assert r is mock_gov
        assert created_count == 1

def test_get_gemini_client_all_cases(monkeypatch):
    """get_gemini_client の正常系、生クライアント None、キャッシュ返却の検証"""
    monkeypatch.setenv("GOOGLE_API_KEY", "my-key")
    
    mock_raw = MagicMock()
    mock_raw.models = MagicMock()
    # spec=GovernedClient を指定することで isinstance(mock_gov, GovernedClient) が True を返すようにする
    mock_gov = MagicMock(spec=GovernedClient)
    mock_gov._raw = mock_raw
    
    with patch("gemini_client_factory._get_raw_client", return_value=mock_raw), \
         patch("gemini_client_factory._create_governed_client_safely", return_value=mock_gov) as mock_create:
        
        # 1. 正常取得
        client1 = get_gemini_client()
        assert client1 is mock_gov
        mock_create.assert_called_once_with(mock_raw)
        
        # 2. キャッシュ取得
        client2 = get_gemini_client()
        assert client2 is mock_gov
        assert mock_create.call_count == 1
        
    # 3. 生クライアントが None の場合
    with patch("gemini_client_factory._get_raw_client", return_value=None):
        # キャッシュを無効化するために reset_client
        reset_client()
        assert get_gemini_client() is None

def test_reset_client(monkeypatch):
    """reset_client によりキャッシュがすべてリセットされること"""
    monkeypatch.setenv("GOOGLE_API_KEY", "reset-key")
    
    mock_raw = MagicMock()
    mock_raw.models = MagicMock()
    
    with patch("gemini_client_factory._create_raw_client", return_value=mock_raw) as mock_create:
        # 初回生成
        assert get_gemini_client() is not None
        assert mock_create.call_count == 1
        
        # キャッシュが効いているため増えない
        assert get_gemini_client() is not None
        assert mock_create.call_count == 1
        
        # リセット実行
        reset_client()
        
        # リセットされたため、再度作成される
        assert get_gemini_client() is not None
        assert mock_create.call_count == 2
