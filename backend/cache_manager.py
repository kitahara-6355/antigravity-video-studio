"""
キャッシュマネージャー

推奨タスク P4.1: Nexusディスパッチ結果キャッシュ
同一入力に対する結果をキャッシュしてAPI呼び出し削減
"""

import hashlib
import json
import time
from typing import Any, Optional, Dict
from functools import wraps
import logging
import threading
import math

logger = logging.getLogger(__name__)


class CacheEntry:
    """キャッシュエントリ"""
    def __init__(self, value: Any, ttl: int = 300, original_key: Optional[str] = None):
        self.value = value
        self.created_at = time.time()
        self.original_key = original_key
        
        # TTLバリデーション強化
        parsed_ttl = 300
        if ttl is not None:
            try:
                parsed_ttl = float(ttl)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid ttl value: {ttl} ({e}). Falling back to default 300.")
                parsed_ttl = 300
        
        if math.isnan(parsed_ttl) or math.isinf(parsed_ttl) or parsed_ttl <= 0:
            logger.warning(f"Out of range or non-finite ttl value: {ttl}. Falling back to default 300.")
            parsed_ttl = 300
            
        self.ttl = parsed_ttl
        self.hits = 0
    
    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl
    
    def touch(self) -> None:
        self.hits += 1


class MemoryCache:
    """インメモリキャッシュ"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._stats: Dict[str, int] = {"hits": 0, "misses": 0}
        self._lock = threading.RLock()
    
    def _make_key(self, key: str) -> str:
        """キーのハッシュ化"""
        if not isinstance(key, str):
            key = str(key)
        return hashlib.sha256(key.encode('utf-8', errors='ignore')).hexdigest()[:16]
    
    def get(self, key: str, default: Any = None) -> Any:
        """キャッシュ取得"""
        with self._lock:
            try:
                hashed_key = self._make_key(key)
                entry = self._cache.get(hashed_key)
                
                if entry is None:
                    self._stats["misses"] += 1
                    return default
                
                # ハッシュ衝突チェック
                if entry.original_key is not None and entry.original_key != key:
                    logger.warning(
                        f"Hash collision detected. Key: '{key}' hashed to '{hashed_key}' "
                        f"which conflicts with existing key '{entry.original_key}'."
                    )
                    self._stats["misses"] += 1
                    return default
                
                if entry.is_expired:
                    del self._cache[hashed_key]
                    self._stats["misses"] += 1
                    return default
                
                entry.touch()
                self._stats["hits"] += 1
                return entry.value
            except Exception as e:
                # TD-671: 恒久的な安全ネットとしての例外捕捉、エラーログ強化
                logger.error(f"Error in cache get: {e}. Self-healing by clearing cache.", exc_info=True)
                try:
                    self.clear()
                except Exception as clear_err:
                    # TD-672: self.clear()自体が例外を投げた場合の捕捉
                    logger.critical(f"Critical error: Failed to clear cache during self-healing: {clear_err}")
                return default
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """キャッシュ設定"""
        with self._lock:
            try:
                if len(self._cache) >= self.max_size:
                    self._evict_expired()
                    if len(self._cache) >= self.max_size:
                        self._evict_lru()
                
                hashed_key = self._make_key(key)
                self._cache[hashed_key] = CacheEntry(value, ttl or self.default_ttl, original_key=key)
            except Exception as e:
                # TD-673: 恒久的な安全ネットとしての例外捕捉
                logger.error(f"Error in cache set: {e}. Self-healing by clearing cache.", exc_info=True)
                try:
                    self.clear()
                except Exception as clear_err:
                    # TD-674: self.clear()自体が例外を投げた場合の捕捉
                    logger.critical(f"Critical error: Failed to clear cache during self-healing: {clear_err}")
    
    def delete(self, key: str) -> bool:
        """キャッシュ削除"""
        with self._lock:
            try:
                hashed_key = self._make_key(key)
                if hashed_key in self._cache:
                    del self._cache[hashed_key]
                    return True
                return False
            except Exception as e:
                # TD-675: 恒久的な安全ネットとしての例外捕捉、ログ強化
                logger.error(f"Error in cache delete: {e}", exc_info=True)
                return False
    
    def clear(self) -> None:
        """全キャッシュクリア"""
        with self._lock:
            try:
                self._cache.clear()
            except Exception as e:
                # TD-676: 恒久的な安全ネットとしての例外捕捉、ログ強化
                logger.error(f"Error in cache clear: {e}", exc_info=True)
    
    def _evict_expired(self) -> int:
        """期限切れエントリ削除 (ロック内でのみ呼び出される想定)"""
        expired_keys = [k for k, v in self._cache.items() if v.is_expired]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)
    
    def _evict_lru(self) -> None:
        """
        最も使用されていないエントリを削除する (ロック内でのみ呼び出される想定)。

        注意: メソッド名はLRU(Least Recently Used)ですが、
        内部的な実装としてはhits(参照回数)が最も少ないものを削除する
        LFU(Least Frequently Used)アルゴリズムとして動作します。
        hitsが同じ場合は、created_atが最も古いものを優先して削除します。
        """
        if not self._cache:
            return
        
        lru_key = min(self._cache.keys(), key=lambda k: (self._cache[k].hits, self._cache[k].created_at))
        del self._cache[lru_key]
    
    @property
    def stats(self) -> Dict[str, Any]:
        """統計情報"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total if total > 0 else 0
            return {
                **self._stats,
                "size": len(self._cache),
                "hit_rate": round(hit_rate, 3)
            }


# グローバルキャッシュインスタンス
dispatch_cache = MemoryCache(max_size=500, default_ttl=300)
api_cache = MemoryCache(max_size=100, default_ttl=60)


def _generate_func_cache_key(func_name: str, args: tuple, kwargs: dict) -> str:
    """デコレータ用のユニークなキャッシュキーを生成する"""
    try:
        # 型混在kwargsのソートでもTypeErrorが起きないように、キーを文字列化してソートする
        sorted_kwargs = sorted(kwargs.items(), key=lambda x: str(x[0]))
        key_data = {
            "func": func_name,
            "args": str(args),
            "kwargs": str(sorted_kwargs)
        }
        return json.dumps(key_data, sort_keys=True)
    except (TypeError, ValueError) as e:
        # より具体的な例外に置き換え（TD-677に関連）
        logger.warning(f"Serialization failed in cache key generation: {e}. Raising exception for fallback.")
        raise
    except Exception as e:
        # 恒久的な安全ネット（想定外の例外）
        logger.error(f"Unexpected error in cache key generation: {e}. Raising exception for fallback.", exc_info=True)
        raise


_MISSING = object()


def cached(cache: MemoryCache = dispatch_cache, ttl: int = None):
    """キャッシュデコレータ"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = None
            try:
                # キャッシュキー生成
                cache_key = _generate_func_cache_key(func.__name__, args, kwargs)
                
                # キャッシュ確認
                cached_result = cache.get(cache_key, default=_MISSING)
                if cached_result is not _MISSING:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cached_result
            except Exception as e:
                # TD-678: キャッシュのルックアップまたはキー生成のエラーを処理。
                # ユーザーの処理には影響させず、ログを残してバイパスする。
                logger.error(f"Cache lookup/key generation failed for {func.__name__}: {e}. Falling back to execution.", exc_info=True)
                # キャッシュをバイパスして実行
                return func(*args, **kwargs)
            
            # 実行して保存
            result = func(*args, **kwargs)
            
            if cache_key is not None:
                try:
                    cache.set(cache_key, result, ttl)
                    logger.debug(f"Cache miss for {func.__name__}, stored result")
                except Exception as e:
                    # TD-679: 保存失敗の例外処理。
                    # 保存失敗は関数の実行結果そのものには影響させないため、ログを残して正常終了する。
                    logger.error(f"Cache store failed for {func.__name__}: {e}", exc_info=True)
            
            return result
        return wrapper
    return decorator
