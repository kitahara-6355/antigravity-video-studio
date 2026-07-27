"""
Redis設定モジュール

推奨タスク F5: Redis接続設定（本番用）
"""

import os
from typing import Optional, Any
import json
import logging
import threading
from urllib.parse import quote

logger = logging.getLogger(__name__)


# redisパッケージの例外を安全に参照するための定義
try:
    import redis
    RedisError = redis.exceptions.RedisError
except ImportError:
    class RedisError(Exception):
        """Fallback RedisError exception when redis package is not installed"""
        pass


class RedisConfig:
    """Redis接続設定"""
    
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        try:
            self.port = int(os.getenv("REDIS_PORT", "6379"))
        except ValueError:
            self.port = 6379
        try:
            self.db = int(os.getenv("REDIS_DB", "0"))
        except ValueError:
            self.db = 0
        self.password = os.getenv("REDIS_PASSWORD", None)
        self.ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        
        self._client = None
    
    @property
    def url(self) -> str:
        """Redis URL生成"""
        scheme = "rediss" if self.ssl else "redis"
        auth = f":{quote(self.password)}@" if self.password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"
    
    def get_client(self):
        """Redis クライアント取得（遅延初期化）"""
        if self._client is None:
            try:
                import redis
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    ssl=self.ssl,
                    decode_responses=True
                )
                # 接続テスト
                self._client.ping()
                logger.info(f"Redis connected: {self.host}:{self.port}")
            except ImportError:
                logger.warning("redis package not installed, using fallback")
                self._client = FallbackCache()
            except redis.exceptions.RedisError as e:
                logger.warning(f"Redis connection failed (RedisError): {e}, using fallback", exc_info=True)
                self._client = FallbackCache()
            except Exception as e:
                logger.error(f"Unexpected error connecting to Redis: {e}, using fallback", exc_info=True)
                self._client = FallbackCache()
        
        return self._client


class FallbackCache:
    """Redis未使用時のフォールバックキャッシュ"""
    
    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()
        logger.info("Using in-memory fallback cache")
    
    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._data.get(key)
    
    def set(self, key: str, value: Any, ex: int = None) -> bool:
        with self._lock:
            self._data[key] = value
            return True
    
    def delete(self, key: str) -> int:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return 1
            return 0
    
    def exists(self, key: str) -> int:
        with self._lock:
            return 1 if key in self._data else 0
    
    def ping(self) -> bool:
        return True
    
    def keys(self, pattern: str = "*") -> list:
        import fnmatch
        with self._lock:
            return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]
    
    def flushdb(self) -> bool:
        with self._lock:
            self._data.clear()
            return True


# グローバル設定
redis_config = RedisConfig()


def get_redis():
    """Redis クライアント取得"""
    return redis_config.get_client()


# 状態管理用ラッパー
class StateStore:
    """Redis/メモリを使った状態管理"""
    
    def __init__(self, prefix: str = "state"):
        self.prefix = prefix
    
    def _key(self, name: str) -> str:
        return f"{self.prefix}:{name}"
    
    def get(self, name: str, default: Any = None) -> Any:
        try:
            client = get_redis()
            value = client.get(self._key(name))
            if value is None:
                return default
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except RedisError as e:
            logger.error(f"StateStore.get failed: {e}", exc_info=True)
            return default
    
    def set(self, name: str, value: Any, ttl: int = None) -> bool:
        try:
            client = get_redis()
            json_value = json.dumps(value)
            return client.set(self._key(name), json_value, ex=ttl)
        except (RedisError, TypeError) as e:
            logger.error(f"StateStore.set failed: {e}", exc_info=True)
            return False
    
    def delete(self, name: str) -> bool:
        try:
            client = get_redis()
            return client.delete(self._key(name)) > 0
        except RedisError as e:
            logger.error(f"StateStore.delete failed: {e}", exc_info=True)
            return False


# 状態ストアインスタンス
dashboard_state = StateStore("dashboard")
session_state = StateStore("session")
