import sys, time, pytest, json
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cache_manager import CacheEntry, MemoryCache, dispatch_cache, api_cache, _generate_func_cache_key, cached

def test_cache_entry_init():
    entry = CacheEntry(value="test_val", ttl=10)
    assert entry.value == "test_val"
    assert entry.ttl == 10
    assert entry.hits == 0
    assert not entry.is_expired
    entry.touch()
    assert entry.hits == 1

def test_cache_entry_expiration():
    entry = CacheEntry(value="test_val", ttl=5)
    assert not entry.is_expired
    with patch("time.time", return_value=time.time() + 6):
        assert entry.is_expired

def test_memory_cache_basic_operations():
    cache = MemoryCache(max_size=3, default_ttl=60)
    assert cache.get("key1") is None
    assert cache.stats["misses"] == 1
    assert cache.stats["hits"] == 0
    assert cache.stats["hit_rate"] == 0.0
    cache.set("key1", "val1")
    assert cache.get("key1") == "val1"
    assert cache.stats["hits"] == 1
    assert cache.stats["misses"] == 1
    assert cache.stats["hit_rate"] == 0.5
    assert cache.stats["size"] == 1
    assert cache.delete("key1") is True
    assert cache.get("key1") is None
    assert cache.delete("key1") is False
    cache.set("key2", "val2")
    cache.clear()
    assert cache.get("key2") is None
    assert cache.stats["size"] == 0

def test_memory_cache_make_key():
    cache = MemoryCache()
    key1 = cache._make_key("123")
    key2 = cache._make_key(123)
    assert key1 == key2
    assert len(key1) == 16

def test_memory_cache_expiration():
    cache = MemoryCache(default_ttl=5)
    cache.set("temp_key", "temp_val")
    with patch("time.time", return_value=time.time() + 10):
        assert cache.get("temp_key") is None
        assert "temp_key" not in cache._cache

def test_memory_cache_eviction_expired():
    cache = MemoryCache(max_size=2, default_ttl=5)
    cache.set("key1", "val1")
    cache.set("key2", "val2")
    original_time = time.time()
    
    # 未来の時刻を返すようにパッチして、期限切れエントリのエビクション（ループ処理）をトリガーする
    with patch("time.time", return_value=original_time + 10):
        cache.set("key3", "val3")
        
    assert len(cache._cache) == 1
    assert cache._make_key("key1") not in cache._cache
    assert cache._make_key("key2") not in cache._cache
    assert cache._make_key("key3") in cache._cache

def test_memory_cache_eviction_lru():
    cache = MemoryCache(max_size=2, default_ttl=100)
    cache.set("key1", "val1")
    cache.set("key2", "val2")
    cache.get("key1")
    cache.set("key3", "val3")
    assert len(cache._cache) == 2
    assert cache._make_key("key2") not in cache._cache
    assert cache._make_key("key1") in cache._cache
    assert cache._make_key("key3") in cache._cache

def test_memory_cache_eviction_lru_with_same_hits():
    cache = MemoryCache(max_size=2, default_ttl=100)
    
    # 異なる created_at をシミュレートするために time.time をパッチして登録する
    base_time = time.time()
    with patch("time.time", return_value=base_time):
        cache.set("key1", "val1")
    with patch("time.time", return_value=base_time + 10):
        cache.set("key2", "val2")
        
    # 両方とも hits は 0 だが、key1 の方が created_at が古い。
    # key3 を追加してエビクションをトリガーする。
    with patch("time.time", return_value=base_time + 20):
        cache.set("key3", "val3")
        
    assert len(cache._cache) == 2
    assert cache._make_key("key1") not in cache._cache
    assert cache._make_key("key2") in cache._cache
    assert cache._make_key("key3") in cache._cache

def test_memory_cache_eviction_lru_empty():
    cache = MemoryCache(max_size=2)
    cache._evict_lru()

def test_memory_cache_exception_handling():
    cache = MemoryCache()
    cache.set("key1", "val1")
    with patch.object(cache, "_make_key", side_effect=Exception("Hashing Error")):
        assert cache.get("key1") is None
        assert len(cache._cache) == 0
    cache.set("key1", "val1")
    with patch.object(cache, "_make_key", side_effect=Exception("Hashing Error")):
        cache.set("key2", "val2")
        assert len(cache._cache) == 0
    cache.set("key1", "val1")
    with patch.object(cache, "_make_key", side_effect=Exception("Hashing Error")):
        assert cache.delete("key1") is False
        assert len(cache._cache) == 1

    # clear()が例外を投げるようにモック化し、get / set の内側の try-except の中の except 節(74-75, 93-94行目)を通す
    with patch.object(cache, "clear", side_effect=Exception("Nested Clear Error")):
        with patch.object(cache, "_make_key", side_effect=Exception("Hashing Error")):
            assert cache.get("key1") is None
            cache.set("key2", "val2")

    # cache._cache を None に差し替えることで、clear() 内の self._cache.clear() で確実に例外を投げ、114-115行目を通す
    original_cache = cache._cache
    cache._cache = None
    try:
        cache.clear()
    finally:
        cache._cache = original_cache

def test_global_instances():
    assert dispatch_cache.max_size == 500
    assert dispatch_cache.default_ttl == 300
    assert api_cache.max_size == 100
    assert api_cache.default_ttl == 60

def test_generate_func_cache_key():
    key1 = _generate_func_cache_key("my_func", (1, "a"), {"y": 20, "x": 10})
    key2 = _generate_func_cache_key("my_func", (1, "a"), {"x": 10, "y": 20})
    assert key1 == key2
    key3 = _generate_func_cache_key("my_func", (1, "b"), {"x": 10, "y": 20})
    # 改善により、型が混在したkwargs（int/str）でもエラーにならずにソートされてキーが生成される
    robust_key = _generate_func_cache_key("my_func", (), {1: "a", "b": 2})
    assert robust_key is not None

def test_cached_decorator_success():
    call_count = 0
    test_cache = MemoryCache()
    @cached(cache=test_cache, ttl=10)
    def my_expensive_func(a, b=2):
        nonlocal call_count
        call_count += 1
        return a + b
    assert my_expensive_func(3, b=4) == 7
    assert call_count == 1
    assert my_expensive_func(3, b=4) == 7
    assert call_count == 1
    assert my_expensive_func(3, b=5) == 8
    assert call_count == 2

def test_cached_decorator_lookup_exception():
    call_count = 0
    test_cache = MemoryCache()
    @cached(cache=test_cache)
    def my_func(x):
        nonlocal call_count
        call_count += 1
        return x * 2
    with patch("cache_manager._generate_func_cache_key", side_effect=Exception("Key Gen Error")):
        assert my_func(5) == 10
        assert call_count == 1
    call_count = 0
    with patch.object(test_cache, "get", side_effect=Exception("Cache Get Error")):
        assert my_func(5) == 10
        assert call_count == 1

def test_cached_decorator_store_exception():
    call_count = 0
    test_cache = MemoryCache()
    @cached(cache=test_cache)
    def my_func(x):
        nonlocal call_count
        call_count += 1
        return x * 2
    with patch.object(test_cache, "set", side_effect=Exception("Cache Set Error")):
        assert my_func(5) == 10
        assert call_count == 1

def test_cached_decorator_none_value():
    call_count = 0
    test_cache = MemoryCache()
    @cached(cache=test_cache)
    def returns_none():
        nonlocal call_count
        call_count += 1
        return None

    # 初回呼び出し：キャッシュミス（実行される）
    assert returns_none() is None
    assert call_count == 1

    # 2回目呼び出し：キャッシュヒット（再実行されない）
    assert returns_none() is None
    assert call_count == 1

def test_cache_entry_invalid_ttl():
    # ttlがNoneの場合
    entry = CacheEntry(value="val", ttl=None)
    assert entry.ttl == 300

    # ttlが文字列で数値変換可能な場合
    entry2 = CacheEntry(value="val", ttl="60")
    assert entry2.ttl == 60.0

    # ttlが不正な文字列の場合（デフォルト値300にフォールバック）
    entry3 = CacheEntry(value="val", ttl="invalid_ttl")
    assert entry3.ttl == 300

    # ttlが数値以外の不正な型の場合（デフォルト値300にフォールバック）
    entry4 = CacheEntry(value="val", ttl=[123])
    assert entry4.ttl == 300

def test_memory_cache_get_default():
    cache = MemoryCache()
    # 存在しないキーに対して指定したデフォルト値を返すか
    assert cache.get("non_existent", default="my_default") == "my_default"

    # キャッシュ期限切れの場合に指定したデフォルト値を返すか
    cache.set("expired_key", "val", ttl=5)
    with patch("time.time", return_value=time.time() + 10):
        assert cache.get("expired_key", default="expired_default") == "expired_default"


def test_cache_entry_invalid_ttl_extended():
    import math
    # NaNのttl
    entry_nan = CacheEntry(value="val", ttl=float("nan"))
    assert entry_nan.ttl == 300
    
    # infのttl
    entry_inf = CacheEntry(value="val", ttl=float("inf"))
    assert entry_inf.ttl == 300

    # 負のttl
    entry_neg = CacheEntry(value="val", ttl=-10)
    assert entry_neg.ttl == 300

    # ゼロのttl
    entry_zero = CacheEntry(value="val", ttl=0)
    assert entry_zero.ttl == 300

def test_generate_func_cache_key_robust_sorting():
    # キーの型が混在したkwargsのソートテスト
    key = _generate_func_cache_key("my_func", (), {"z_key": 1, 123: "a"})
    assert "z_key" in key
    assert "123" in key

def test_memory_cache_hash_collision():
    cache = MemoryCache()
    # 同一ハッシュ値を持つが、元のキーが異なる二つのエントリを模倣
    # _make_key が同じ値を返すようにモックする
    with patch.object(cache, "_make_key", return_value="collision_hash"):
        cache.set("key_a", "value_a")
        # 元のキー比較により、ハッシュが同じでも key_b の取得はミスになるべき
        assert cache.get("key_b") is None
        # key_a は元のキーが一致するので value_a が返るべき
        assert cache.get("key_a") == "value_a"

