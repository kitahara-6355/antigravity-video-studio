import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from cache_manager import MemoryCache, cached, dispatch_cache

# 1. シリアライズ不可能なオブジェクトを定義
class UnserializableObj:
    def __str__(self):
        # sorted() や str() などの処理時に例外を発生させる
        raise TypeError("Cannot represent as string")
    def __repr__(self):
        raise TypeError("Cannot represent as repr")

class TestCacheRecovery:
    
    # 1. キー生成例外時の自動フォールバック検証
    def test_key_generation_fallback(self):
        call_count = 0
        
        @cached(cache=dispatch_cache)
        def my_func(x, bad_val):
            nonlocal call_count
            call_count += 1
            return x
            
        obj = UnserializableObj()
        # クラッシュせずに実行できること
        res = my_func(42, obj)
        assert res == 42
        assert call_count == 1
        
        # キャッシュには保存されないため、2回目も my_func が直接実行される
        res2 = my_func(42, obj)
        assert res2 == 42
        assert call_count == 2

    # 2. キャッシュ破損時の自己修復とフォールバック検証
    def test_cache_corruption_self_healing(self):
        custom_cache = MemoryCache()
        
        @cached(cache=custom_cache)
        def target_func(a):
            return a * 2
            
        # 1回目は正常に動作
        assert target_func(5) == 10
        cache_keys = list(custom_cache._cache.keys())
        assert len(cache_keys) > 0
        assert custom_cache._cache.get(cache_keys[0]) is not None
        
        # キャッシュの内部データを意図的に破損させ、getメソッドで例外を起こす
        with patch.object(custom_cache, "_make_key", side_effect=RuntimeError("Corruption simulation")):
            with patch.object(custom_cache, "clear", wraps=custom_cache.clear) as mock_clear:
                res = target_func(5)
                # クラッシュせずにフォールバックすること
                assert res == 10
                # clear() が呼び出されていること
                assert mock_clear.call_count >= 1
                
        # 破損修復後、キャッシュがクリアされていること
        assert len(custom_cache._cache) == 0

    # 3. スレッドセーフティの検証
    def test_cache_thread_safety(self):
        cache = MemoryCache(max_size=50)
        errors = []
        stop_event = threading.Event()
        
        def writer():
            try:
                for i in range(1000):
                    if stop_event.is_set():
                        break
                    cache.set(f"key_{i % 100}", i)
            except Exception as e:
                errors.append(f"Writer error: {e}")
                
        def reader():
            try:
                for i in range(1000):
                    if stop_event.is_set():
                        break
                    cache.get(f"key_{i % 100}")
            except Exception as e:
                errors.append(f"Reader error: {e}")
                
        def deleter():
            try:
                for i in range(500):
                    if stop_event.is_set():
                        break
                    cache.delete(f"key_{i % 100}")
                    if i % 10 == 0:
                        cache.clear()
            except Exception as e:
                errors.append(f"Deleter error: {e}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=deleter)
        ]
        
        for t in threads:
            t.start()
            
        time.sleep(0.5)
        stop_event.set()
        
        for t in threads:
            t.join()
            
        assert len(errors) == 0, f"Thread-safety violations detected: {errors}"

    # 4. 非文字列キーのハッシュ化の検証
    def test_non_string_key_hashing(self):
        cache = MemoryCache()
        # 数値キー
        cache.set(123, "value_123")
        assert cache.get(123) == "value_123"
        # タプルキー
        cache.set((1, 2, 3), "value_tuple")
        assert cache.get((1, 2, 3)) == "value_tuple"

    # 5. 期限切れエントリへのアクセス時の挙動検証
    def test_expired_entry_retrieval(self):
        cache = MemoryCache()
        # TTLを0秒にして設定
        cache.set("expired_key", "val", ttl=-1)
        # statsの初期状態
        initial_misses = cache.stats["misses"]
        
        # 期限切れのためNoneが返るはず
        assert cache.get("expired_key") is None
        # キャッシュから削除されていること
        assert len(cache._cache) == 0
        # missesがカウントアップされていること
        assert cache.stats["misses"] == initial_misses + 1

    # 6. キャッシュget時の例外発生、かつclear()失敗時のハンドリング検証
    def test_cache_get_exception_and_clear_failure(self):
        cache = MemoryCache()
        cache.set("key", "val")
        
        # get() 内で make_key が例外を投げるようにし、さらに clear() も例外を投げるようにモック
        with patch.object(cache, "_make_key", side_effect=RuntimeError("Get failed")):
            with patch.object(cache, "clear", side_effect=RuntimeError("Clear failed")):
                res = cache.get("key")
                # クラッシュせずにNoneを返すこと
                assert res is None

    # 7. キャッシュset時の例外発生、かつclear()失敗時のハンドリング検証
    def test_cache_set_exception_and_clear_failure(self):
        cache = MemoryCache()
        
        # set() 内で make_key が例外を投げるようにし、さらに clear() も例外を投げるようにモック
        with patch.object(cache, "_make_key", side_effect=RuntimeError("Set failed")):
            with patch.object(cache, "clear", side_effect=RuntimeError("Clear failed")):
                # 例外が発生してもクラッシュしないこと
                cache.set("key", "val")

    # 8. キャッシュdelete時の例外ハンドリング検証
    def test_cache_delete_exception(self):
        cache = MemoryCache()
        cache.set("key", "val")
        
        with patch.object(cache, "_make_key", side_effect=RuntimeError("Delete failed")):
            res = cache.delete("key")
            # deleteが例外で失敗した場合はFalseを返すこと
            assert res is False

    # 9. キャッシュclear時の例外ハンドリング検証
    def test_cache_clear_exception(self):
        cache = MemoryCache()
        # _cache を dict から mock に差し替え
        mock_cache_dict = MagicMock()
        mock_cache_dict.clear.side_effect = RuntimeError("Dict clear failed")
        cache._cache = mock_cache_dict
        
        # 例外が発生してもクラッシュしないこと
        cache.clear()
        assert mock_cache_dict.clear.called

    # 10. キャッシュ溢れ時の期限切れエントリ削除ループ処理検証
    def test_evict_expired_loop(self):
        # max_size=2
        cache = MemoryCache(max_size=2)
        # 1つ目は有効期限切れにする
        cache.set("key1", "val1", ttl=-1)
        # 2つ目は有効
        cache.set("key2", "val2", ttl=100)
        
        # 3つ目を追加した時、max_sizeを超過するため _evict_expired が走り、期限切れの key1 が消えるはず
        cache.set("key3", "val3", ttl=100)
        
        # key1 は削除されて取得できないはず
        assert cache.get("key1") is None
        # key2, key3 は残っているはず
        assert cache.get("key2") == "val2"
        assert cache.get("key3") == "val3"
        assert len(cache._cache) == 2

    # 11. 空キャッシュでの _evict_lru 検証
    def test_evict_lru_with_empty_cache(self):
        cache = MemoryCache()
        # _cache が空の状態で _evict_lru() を呼び出しても例外が発生しないこと
        assert len(cache._cache) == 0
        cache._evict_lru()  # 即時リターンされるはず
        assert len(cache._cache) == 0

    # 12. キャッシュ統計情報の計算検証
    def test_cache_stats_calculation(self):
        cache = MemoryCache()
        
        # hits=0, misses=0 の初期状態
        stats = cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        
        # hits > 0, misses > 0 にする
        cache.set("key", "val")
        cache.get("key")      # hit + 1
        cache.get("invalid")  # miss + 1
        
        stats2 = cache.stats
        assert stats2["hits"] == 1
        assert stats2["misses"] == 1
        assert stats2["hit_rate"] == 0.5

    # 13. デコレータでのキャッシュヒットと保存失敗の検証
    def test_cached_decorator_hit_and_store_failure(self):
        custom_cache = MemoryCache()
        
        call_count = 0
        @cached(cache=custom_cache)
        def my_func(x):
            nonlocal call_count
            call_count += 1
            return x
            
        # 1回目：キャッシュミスして実行
        assert my_func(10) == 10
        assert call_count == 1
        
        # 2回目：キャッシュヒットして、元の関数は呼ばれない
        with patch('logging.Logger.debug') as mock_debug:
            assert my_func(10) == 10
            assert call_count == 1
            # logger.debug(f"Cache hit for my_func") が呼ばれたはず
            mock_debug.assert_any_call("Cache hit for my_func")
            
        # 3回目：キャッシュ保存時（set）に例外が発生した場合のハンドリング
        # 引数に別の値を入れてキャッシュミスを起こし、set() のタイミングで例外を投げる
        with patch.object(custom_cache, "set", side_effect=RuntimeError("Store failed")):
            with patch('logging.Logger.error') as mock_error:
                assert my_func(20) == 20
                # キャッシュ保存失敗がログ出力されるがクラッシュはしない
                mock_error.assert_any_call("Cache store failed for my_func: Store failed")

    # 14. キャッシュ溢れ時のLRU(実際はLFU)削除アルゴリズムの動作検証
    def test_evict_lru_behavior(self):
        cache = MemoryCache(max_size=3)
        
        # 3つのエントリを追加
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.set("key3", "val3")
        
        # hits を増やす
        cache.get("key1")  # key1 hits -> 1
        cache.get("key1")  # key1 hits -> 2
        cache.get("key2")  # key2 hits -> 1
        # key3 hits -> 0 (アクセスなし)
        
        # 4つ目のエントリを追加。期限切れはないので、hitsが最小の key3 (hits=0) が消えるはず
        cache.set("key4", "val4")
        
        assert cache.get("key3") is None
        assert cache.get("key1") == "val1"
        assert cache.get("key2") == "val2"
        assert cache.get("key4") == "val4"
        
        # 現在の状態：
        # key1: hits=3 (getされたため増える。Created時0 -> get(x2)で2 -> 削除後のgetで3)
        # key2: hits=2 (getされたため増える。Created時0 -> get(x1)で1 -> 削除後のgetで2)
        # key4: hits=1 (getされたため増える。Created時0 -> 削除後のgetで1)
        # ここで key4 をさらに get して hits を 3 に増やす
        cache.get("key4")  # key4 hits -> 2
        cache.get("key4")  # key4 hits -> 3
        
        # 現在の状態：
        # key1: hits=3
        # key2: hits=2
        # key4: hits=3
        # ここで key5 を追加すると、最小hitsの key2 (hits=2) が消えるはず
        cache.set("key5", "val5")
        
        assert cache.get("key2") is None
        assert cache.get("key1") == "val1"
        assert cache.get("key4") == "val4"
        assert cache.get("key5") == "val5"


