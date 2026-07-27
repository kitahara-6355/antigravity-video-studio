"""
M2.5: Redis Config & State Store テスト — 15テスト

redis_config.py (68 stmts, missed 45 → 34%) のカバレッジ改善。
FallbackCache, RedisConfig, StateStore の全メソッドを網羅。

外部依存: Redis → FallbackCacheにフォールバック（自動）。
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from redis_config import FallbackCache, RedisConfig, StateStore, RedisError


# ============================================================
# FallbackCache テスト
# ============================================================

class TestFallbackCache:
    """FallbackCache: インメモリフォールバック"""

    def test_set_and_get(self):
        """set → get"""
        cache = FallbackCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self):
        """get: 存在しないキー → None"""
        cache = FallbackCache()
        assert cache.get("nonexistent") is None

    def test_delete_existing(self):
        """delete: 存在するキー → 1"""
        cache = FallbackCache()
        cache.set("key1", "value1")
        assert cache.delete("key1") == 1
        assert cache.get("key1") is None

    def test_delete_nonexistent(self):
        """delete: 存在しないキー → 0"""
        cache = FallbackCache()
        assert cache.delete("nonexistent") == 0

    def test_exists_true(self):
        """exists: 存在するキー → 1"""
        cache = FallbackCache()
        cache.set("key1", "value1")
        assert cache.exists("key1") == 1

    def test_exists_false(self):
        """exists: 存在しないキー → 0"""
        cache = FallbackCache()
        assert cache.exists("nonexistent") == 0

    def test_ping(self):
        """ping: 常にTrue"""
        cache = FallbackCache()
        assert cache.ping() is True

    def test_keys_pattern(self):
        """keys: パターンマッチ"""
        cache = FallbackCache()
        cache.set("state:task1", "v1")
        cache.set("state:task2", "v2")
        cache.set("config:key1", "v3")
        assert len(cache.keys("state:*")) == 2
        assert len(cache.keys("config:*")) == 1

    def test_flushdb(self):
        """flushdb: 全データ削除"""
        cache = FallbackCache()
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        assert cache.flushdb() is True
        assert cache.get("key1") is None


# ============================================================
# StateStore テスト
# ============================================================

class TestStateStore:
    """StateStore: Redis/メモリ状態管理"""

    def test_set_and_get_string(self):
        """set/get: 文字列"""
        store = StateStore(prefix="test")
        store.set("name", "テスト値")
        assert store.get("name") == "テスト値"

    def test_set_and_get_dict(self):
        """set/get: 辞書 → JSONシリアライズ"""
        store = StateStore(prefix="test")
        store.set("data", {"key": "value", "count": 42})
        result = store.get("data")
        assert result["key"] == "value"
        assert result["count"] == 42

    def test_get_default(self):
        """get: 存在しないキー → default"""
        store = StateStore(prefix="test")
        assert store.get("nonexistent", default="fallback") == "fallback"

    def test_delete(self):
        """delete: キー削除"""
        store = StateStore(prefix="test")
        store.set("to_delete", "temp")
        assert store.delete("to_delete") is True
        assert store.get("to_delete") is None

    def test_key_prefix(self):
        """_key: プレフィックス付きキー"""
        store = StateStore(prefix="myapp")
        assert store._key("session") == "myapp:session"

    def test_isolation_between_stores(self):
        """異なるプレフィックスのストアは独立"""
        store_a = StateStore(prefix="a")
        store_b = StateStore(prefix="b")
        store_a.set("key", "val_a")
        store_b.set("key", "val_b")
        assert store_a.get("key") == "val_a"
        assert store_b.get("key") == "val_b"

    def test_get_invalid_json_returns_raw_string(self):
        """JSONとしてパースできない値が渡された場合、生の文字列をそのまま返す"""
        store = StateStore(prefix="test")
        client = store.get("nonexistent")  # ensure client is initialized
        from redis_config import get_redis
        client = get_redis()
        client.set(store._key("bad_json"), "{invalid_json")
        
        result = store.get("bad_json")
        assert result == "{invalid_json"

    def test_set_primitive_values(self):
        """dict/list以外のプリミティブ値が正しく保存・復元される"""
        store = StateStore(prefix="test")
        
        # 整数
        store.set("integer", 42)
        assert store.get("integer") == 42
        
        # 真偽値
        store.set("boolean", True)
        assert store.get("boolean") is True
        
        # 浮動小数点数
        store.set("float", 3.14)
        assert store.get("float") == 3.14

    def test_string_numeric_issue(self):
        """数字だけの文字列を保存した場合、取得時に型が数値になってしまわないか確認"""
        store = StateStore(prefix="test")
        store.set("numeric_str", "12345")
        # 現状の挙動を確認するためにアサートしてみる
        val = store.get("numeric_str")
        assert val == "12345"

# ============================================================
# RedisConfig & get_redis テスト（カバレッジ改善用）
# ============================================================

class TestRedisConfigAndClient:
    """RedisConfig の URL 生成および get_client のテスト"""

    def test_url_generation_default(self):
        """デフォルト設定での URL 生成"""
        config = RedisConfig()
        config.ssl = False
        config.password = None
        assert config.url == f"redis://{config.host}:{config.port}/{config.db}"

    def test_url_generation_ssl_and_password(self):
        """SSLおよびパスワードありでの URL 生成"""
        config = RedisConfig()
        config.ssl = True
        config.password = "secret"
        assert config.url == f"rediss://:secret@{config.host}:{config.port}/{config.db}"

    @patch.dict("sys.modules", {"redis": MagicMock()})
    def test_get_client_success(self):
        """redisパッケージが存在し、接続成功時の動作"""
        import sys
        mock_redis = sys.modules["redis"]
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.Redis.return_value = mock_client

        config = RedisConfig()
        config._client = None
        client = config.get_client()

        assert client == mock_client
        mock_redis.Redis.assert_called_once_with(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            ssl=config.ssl,
            decode_responses=True
        )
        mock_client.ping.assert_called_once()

    @patch.dict("sys.modules", {"redis": MagicMock()})
    def test_get_client_redis_error(self):
        """RedisError 発生時に FallbackCache が返る動作"""
        import sys
        mock_redis = sys.modules["redis"]
        
        class MockRedisError(Exception):
            pass
            
        mock_redis.exceptions = MagicMock()
        mock_redis.exceptions.RedisError = MockRedisError
        
        mock_client = MagicMock()
        mock_client.ping.side_effect = MockRedisError("Connection refused")
        mock_redis.Redis.return_value = mock_client

        config = RedisConfig()
        config._client = None
        client = config.get_client()

        assert isinstance(client, FallbackCache)

    @patch("redis_config.redis_config")
    def test_get_redis_wrapper(self, mock_global_config):
        """get_redis 関数がグローバル設定 of get_client を呼び出すこと"""
        from redis_config import get_redis
        mock_client = MagicMock()
        mock_global_config.get_client.return_value = mock_client
        
        assert get_redis() == mock_client
        mock_global_config.get_client.assert_called_once()

    def test_get_client_import_error(self):
        """redisパッケージがインストールされていない（ImportError）場合の動作"""
        import sys
        from unittest.mock import patch
        with patch.dict("sys.modules", {"redis": None}):
            config = RedisConfig()
            config._client = None
            client = config.get_client()
            assert isinstance(client, FallbackCache)

    def test_redis_config_env_loading(self):
        """環境変数から接続設定が正しくロードされること"""
        import os
        from unittest.mock import patch
        env_vars = {
            "REDIS_HOST": "my-redis-host",
            "REDIS_PORT": "1234",
            "REDIS_DB": "5",
            "REDIS_PASSWORD": "my-password",
            "REDIS_SSL": "true",
        }
        with patch.dict("os.environ", env_vars):
            config = RedisConfig()
            assert config.host == "my-redis-host"
            assert config.port == 1234
            assert config.db == 5
            assert config.password == "my-password"
            assert config.ssl is True
            assert config.url == "rediss://:my-password@my-redis-host:1234/5"
            
        env_vars_no_ssl = {
            "REDIS_HOST": "my-redis-host",
            "REDIS_PORT": "1234",
            "REDIS_DB": "5",
            "REDIS_PASSWORD": "my-password",
            "REDIS_SSL": "FALSE",
        }
        with patch.dict("os.environ", env_vars_no_ssl):
            config = RedisConfig()
            assert config.ssl is False
            assert config.url == "redis://:my-password@my-redis-host:1234/5"

    def test_redis_config_env_loading_invalid(self):
        """環境変数に無効な値が設定された場合のフォールバック動作"""
        import os
        from unittest.mock import patch
        env_vars = {
            "REDIS_PORT": "not_an_int",
            "REDIS_DB": "not_an_int_either",
        }
        with patch.dict("os.environ", env_vars):
            config = RedisConfig()
            assert config.port == 6379
            assert config.db == 0

    def test_state_store_delete_nonexistent(self):
        """存在しないキーを削除しようとした場合の動作"""
        store = StateStore(prefix="test")
        assert store.delete("nonexistent_key_xyz") is False

    def test_state_store_set_with_ttl(self):
        """StateStore.set で ttl を指定した場合の動作"""
        store = StateStore(prefix="test")
        client = store.get("nonexistent")
        from redis_config import get_redis
        client = get_redis()
        
        with patch.object(client, "set", return_value=True) as mock_set:
            assert store.set("ttl_key", "value", ttl=3600) is True
            mock_set.assert_called_once_with(store._key("ttl_key"), '"value"', ex=3600)

    def test_fallback_cache_set_with_ex(self):
        """FallbackCache.set で ex 引数（有効期限）を渡した場合の動作"""
        cache = FallbackCache()
        assert cache.set("ex_key", "value", ex=10) is True
        assert cache.get("ex_key") == "value"

    def test_redis_config_default_initialization(self):
        """環境変数が設定されていない場合のデフォルト初期化設定を検証"""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            config = RedisConfig()
            assert config.host == "localhost"
            assert config.port == 6379
            assert config.db == 0
            assert config.password is None
            assert config.ssl is False

    def test_fallback_cache_keys_default_pattern(self):
        """FallbackCache.keys でパターンを指定しない場合にデフォルトで '*' が使われることを検証"""
        cache = FallbackCache()
        cache.set("key1", "v1")
        cache.set("key2", "v2")
        keys = cache.keys()
        assert "key1" in keys
        assert "key2" in keys
        assert len(keys) == 2

    def test_state_store_default_prefix(self):
        """StateStore がデフォルトのプレフィックス 'state' で初期化されることを検証"""
        store = StateStore()
        assert store.prefix == "state"
        assert store._key("name") == "state:name"

    def test_state_store_get_type_error_handling(self):
        """StateStore.get において json.loads が TypeError を発生させた際に生の値が返ることを検証"""
        store = StateStore(prefix="test")
        with patch("json.loads", side_effect=TypeError("mocked type error")):
            from redis_config import get_redis
            client = get_redis()
            client.set(store._key("type_error_key"), "raw_unparsable_value")
            
            result = store.get("type_error_key")
            assert result == "raw_unparsable_value"

    def test_url_generation_password_with_special_characters(self):
        """パスワードに特殊文字（@や:など）が含まれる場合にURLエンコードされることを検証"""
        config = RedisConfig()
        config.ssl = False
        config.password = "pass@word:123"
        assert "pass%40word%3A123" in config.url

    def test_fallback_cache_multithreaded_safety(self):
        """FallbackCache がマルチスレッド環境下で並行アクセスされた際のスレッドセーフ性を検証"""
        import threading
        import time
        cache = FallbackCache()
        
        errors = []
        
        def worker(thread_id):
            try:
                for i in range(100):
                    key = f"thread_{thread_id}_key_{i}"
                    cache.set(key, f"val_{i}")
                    cache.get(key)
                    cache.exists(key)
                    cache.keys(f"thread_{thread_id}_*")
                    if i % 10 == 0:
                        cache.delete(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Multithreading errors detected: {errors}"

    @patch("redis_config.get_redis")
    def test_state_store_exception_handling_fallback(self, mock_get_redis):
        """StateStore の各メソッドで RedisError が発生した際に、クラッシュせず適切にフォールバックされることを検証"""
        mock_client = MagicMock()
        mock_client.get.side_effect = RedisError("Redis connection lost")
        mock_client.set.side_effect = RedisError("Redis connection lost")
        mock_client.delete.side_effect = RedisError("Redis connection lost")
        mock_get_redis.return_value = mock_client

        store = StateStore(prefix="test_err")
        
        # get の例外ハンドリング検証
        assert store.get("key", default="fallback_val") == "fallback_val"
        
        # set の例外ハンドリング検証
        assert store.set("key", "value") is False
        
        # delete の例外ハンドリング検証
        assert store.delete("key") is False

    @patch("redis_config.get_redis")
    def test_state_store_other_exceptions_propagate(self, mock_get_redis):
        """StateStore の各メソッドで RedisError 以外の一般的な例外が発生した際に、例外が呼び出し元に伝播することを検証"""
        mock_client = MagicMock()
        mock_client.get.side_effect = RuntimeError("Unexpected error")
        mock_client.set.side_effect = RuntimeError("Unexpected error")
        mock_client.delete.side_effect = RuntimeError("Unexpected error")
        mock_get_redis.return_value = mock_client

        store = StateStore(prefix="test_err")
        
        # get
        with pytest.raises(RuntimeError):
            store.get("key")
            
        # set
        with pytest.raises(RuntimeError):
            store.set("key", "value")
            
        # delete
        with pytest.raises(RuntimeError):
            store.delete("key")

    @patch.dict("sys.modules", {"redis": MagicMock()})
    def test_get_client_generic_exception_fallback(self):
        """get_clientにおいてRedisError以外の汎用的な例外（例: SSLError）が発生した際、FallbackCacheにフォールバックすることを検証"""
        import sys
        mock_redis = sys.modules["redis"]
        
        class MockRedisError(Exception):
            pass
            
        mock_redis.exceptions = MagicMock()
        mock_redis.exceptions.RedisError = MockRedisError
        
        # Redisのインスタンス化またはpingでSSLErrorを模した一般的なExceptionをスローさせる
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("Generic SSLError or ConnectionError")
        mock_redis.Redis.return_value = mock_client

        config = RedisConfig()
        config._client = None
        client = config.get_client()

        assert isinstance(client, FallbackCache)
