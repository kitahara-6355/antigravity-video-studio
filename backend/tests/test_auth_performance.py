"""
認証テスト

推奨タスク R5.2: 認証フローテスト
推奨タスク R5.3: パフォーマンステスト
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock


class TestWebSocketAuth:
    """WebSocket認証テスト"""
    
    def test_token_generation(self):
        """トークン生成"""
        from websocket_handler import token_manager
        
        token = token_manager.generate_token("user_123", ttl=3600)
        assert token is not None
        assert len(token) > 20
    
    def test_token_validation(self):
        """トークン検証"""
        from websocket_handler import token_manager
        
        token = token_manager.generate_token("user_456", ttl=3600)
        user_id = token_manager.validate_token(token)
        assert user_id == "user_456"
    
    def test_invalid_token(self):
        """無効トークン"""
        from websocket_handler import token_manager
        
        user_id = token_manager.validate_token("invalid_token_123")
        assert user_id is None
    
    def test_token_revocation(self):
        """トークン無効化"""
        from websocket_handler import token_manager
        
        token = token_manager.generate_token("user_789", ttl=3600)
        assert token_manager.validate_token(token) is not None
        
        token_manager.revoke_token(token)
        assert token_manager.validate_token(token) is None


class TestConnectionLimits:
    """接続制限テスト"""
    
    def test_max_connections_config(self):
        """最大接続数設定"""
        from websocket_handler import MAX_CONNECTIONS, MAX_CONNECTIONS_PER_USER
        
        assert MAX_CONNECTIONS == 100
        assert MAX_CONNECTIONS_PER_USER == 5
    
    def test_connection_manager_stats(self):
        """接続統計"""
        from websocket_handler import ConnectionManager
        
        manager = ConnectionManager(max_connections=10)
        stats = manager.get_stats()
        
        assert "total_connections" in stats
        assert "max_connections" in stats
        assert stats["max_connections"] == 10


class TestPerformance:
    """パフォーマンステスト（R5.3）"""
    
    def test_cache_performance(self):
        """キャッシュパフォーマンス"""
        from cache_manager import MemoryCache
        
        cache = MemoryCache(max_size=1000)
        
        # 書き込みパフォーマンス
        start = time.time()
        for i in range(1000):
            cache.set(f"key_{i}", f"value_{i}")
        write_time = time.time() - start
        
        assert write_time < 1.0, f"Write too slow: {write_time}s"
        
        # 読み込みパフォーマンス
        start = time.time()
        for i in range(1000):
            cache.get(f"key_{i}")
        read_time = time.time() - start
        
        assert read_time < 0.5, f"Read too slow: {read_time}s"
    
    def test_cache_hit_rate(self):
        """キャッシュヒット率"""
        from cache_manager import MemoryCache
        
        cache = MemoryCache(max_size=100)
        
        # データ投入
        for i in range(50):
            cache.set(f"key_{i}", f"value_{i}")
        
        # 読み込み（ヒットするはず）
        for i in range(50):
            cache.get(f"key_{i}")
        
        stats = cache.stats
        assert stats["hit_rate"] >= 0.9, f"Hit rate too low: {stats['hit_rate']}"
    
    def test_log_manager_performance(self):
        """ログマネージャーパフォーマンス"""
        from log_manager import MemoryLogHandler
        import logging
        
        handler = MemoryLogHandler(max_entries=1000)
        handler.setFormatter(logging.Formatter('%(message)s'))
        
        # ログ書き込み
        start = time.time()
        for i in range(1000):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=f"Test message {i}",
                args=(),
                exc_info=None
            )
            handler.emit(record)
        write_time = time.time() - start
        
        assert write_time < 1.0, f"Log write too slow: {write_time}s"
        
        # ログ読み込み
        start = time.time()
        logs = handler.get_logs(limit=100)
        read_time = time.time() - start
        
        assert read_time < 0.1, f"Log read too slow: {read_time}s"
        assert len(logs) == 100


class TestErrorReporting:
    """エラー報告テスト"""
    
    def test_report_and_resolve(self):
        """レポートと解決"""
        from error_reporter import ErrorReportManager
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ErrorReportManager(report_dir=tmpdir)
            
            # レポート作成
            report_id = manager.report_error(
                error_type="test_error",
                message="Test error message"
            )
            assert report_id is not None
            
            # 未解決リスト
            unresolved = manager.get_unresolved()
            assert len(unresolved) == 1
            
            # 解決
            manager.resolve_error(report_id, "Fixed")
            unresolved = manager.get_unresolved()
            assert len(unresolved) == 0
    
    def test_faq_search(self):
        """FAQ検索"""
        from error_reporter import faq_manager
        
        results = faq_manager.search("接続できません")
        assert len(results) > 0
        assert "接続" in results[0].question


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
