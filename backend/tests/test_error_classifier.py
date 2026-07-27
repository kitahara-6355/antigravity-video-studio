import os
import sys
import json
import pytest

# プロジェクトルートを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.error_classifier import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorAction

def test_classify_api_rate_limit():
    # 429 エラーメッセージを持つ一般的な例外
    exc = Exception("API rate limit exceeded: status_code=429, Too Many Requests")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.API_RATE_LIMIT
    assert result.severity == ErrorSeverity.MAJOR
    assert result.action == ErrorAction.RETRY
    assert "429" in result.reason

def test_classify_network_timeout():
    # タイムアウト関連のエラー
    exc = TimeoutError("Request timed out after 30.0 seconds")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.NETWORK_TIMEOUT
    assert result.severity == ErrorSeverity.MAJOR
    assert result.action == ErrorAction.RETRY
    assert "timeout" in result.reason.lower()

def test_classify_json_decode_error():
    # JSONパース失敗
    try:
        json.loads("{ invalid json }")
    except json.JSONDecodeError as exc:
        result = ErrorClassifier.classify(exc)
        
        assert result.category == ErrorCategory.DATA_CORRUPTION
        assert result.severity == ErrorSeverity.MODERATE
        assert result.action == ErrorAction.FALLBACK
        assert "JSONDecodeError" in result.reason

def test_classify_file_io_error():
    # ファイルIO関連のエラー
    exc = PermissionError("[Errno 13] Permission denied: 'temp_file.txt'")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.FILE_IO_ERROR
    assert result.severity == ErrorSeverity.MAJOR
    assert result.action == ErrorAction.CLEANUP_AND_RETRY
    assert "PermissionError" in result.reason

def test_classify_database_error():
    # DB接続エラー等の分類
    exc = Exception("OperationalError: database is locked")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.DATABASE_ERROR
    assert result.severity == ErrorSeverity.MAJOR
    assert result.action == ErrorAction.RETRY
    assert "database" in result.reason.lower()

def test_classify_authentication_error():
    # 認証エラーの分類
    exc = Exception("403 Forbidden: Invalid API Key")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.AUTHENTICATION_ERROR
    assert result.severity == ErrorSeverity.CRITICAL
    assert result.action == ErrorAction.FATAL_FAIL
    assert "Forbidden" in result.reason

def test_classify_resource_exhausted():
    # リソース枯渇（ディスクフル等）の分類
    exc = Exception("OSError: [Errno 28] No space left on device")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.RESOURCE_EXHAUSTED
    assert result.severity == ErrorSeverity.CRITICAL
    assert result.action == ErrorAction.CLEANUP_AND_RETRY
    assert "space" in result.reason.lower()

def test_classify_bad_stringify_exception():
    # __str__ が例外をスローする極悪な例外オブジェクトに対する堅牢性テスト
    class EvilException(Exception):
        def __str__(self):
            raise RuntimeError("Evil string representation failure")
            
    exc = EvilException("This will fail to stringify")
    result = ErrorClassifier.classify(exc)
    
    # クラッシュせず、安全に何らかのカテゴリ（おそらくUNKNOWNまたはEvilExceptionのクラス名から判定）を返すこと
    assert result.original_exception == exc
    assert "EvilException" in result.reason

def test_classify_internal_failure(monkeypatch):
    # ErrorClassifier 内部で例外が発生した場合のフォールバック動作を検証
    # json.JSONDecodeError をクラスではないオブジェクトにモックすることで、
    # isinstance チェック時に TypeError を発生させる
    monkeypatch.setattr(json, "JSONDecodeError", "not a class")
    
    exc = Exception("Normal exception")
    result = ErrorClassifier.classify(exc)
    
    assert result.category == ErrorCategory.UNKNOWN
    assert result.severity == ErrorSeverity.CRITICAL
    assert result.action == ErrorAction.FATAL_FAIL
    assert "internal failure" in result.reason.lower()

def test_classify_exception_group():
    # 1. タイムアウト単一を含むExceptionGroup
    exc = ExceptionGroup("group1", [TimeoutError("timed out")])
    result = ErrorClassifier.classify(exc)
    assert result.category == ErrorCategory.NETWORK_TIMEOUT
    assert result.severity == ErrorSeverity.MAJOR
    assert result.action == ErrorAction.RETRY
    assert "ExceptionGroup contains" in result.reason
    assert "network_timeout" in result.reason
    assert result.original_exception == exc

    # 2. リトライ可能と致命的エラーが混在するExceptionGroup
    exc_mixed = ExceptionGroup("group2", [
        TimeoutError("timed out"),
        ValueError("fatal parsing error")
    ])
    result_mixed = ErrorClassifier.classify(exc_mixed)
    # ValueErrorはUNKNOWN(CRITICAL/FATAL_FAIL)に分類されるため、それが最優先される
    assert result_mixed.category == ErrorCategory.UNKNOWN
    assert result_mixed.severity == ErrorSeverity.CRITICAL
    assert result_mixed.action == ErrorAction.FATAL_FAIL
    assert result_mixed.original_exception == exc_mixed

    # 3. 空のExceptionGroup (万が一のガードレール)
    class DummyExceptionGroup(BaseExceptionGroup):
        def __new__(cls):
            return super().__new__(cls, "empty", [ValueError("dummy")])
        @property
        def exceptions(self):
            return []
            
    exc_empty = DummyExceptionGroup()
    result_empty = ErrorClassifier.classify(exc_empty)
    assert result_empty.category == ErrorCategory.UNKNOWN
    assert result_empty.severity == ErrorSeverity.CRITICAL
    assert result_empty.action == ErrorAction.FATAL_FAIL

def test_classify_oserror_network_subclasses():
    import socket
    import ssl
    
    # socket.gaierror
    exc_gai = socket.gaierror(11001, "getaddrinfo failed")
    result_gai = ErrorClassifier.classify(exc_gai)
    assert result_gai.category == ErrorCategory.NETWORK_TIMEOUT
    assert result_gai.action == ErrorAction.RETRY

    # ssl.SSLError
    exc_ssl = ssl.SSLError("SSL validation failed")
    result_ssl = ErrorClassifier.classify(exc_ssl)
    assert result_ssl.category == ErrorCategory.NETWORK_TIMEOUT
    assert result_ssl.action == ErrorAction.RETRY
