import json
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

class ErrorCategory(Enum):
    API_RATE_LIMIT = "api_rate_limit"
    NETWORK_TIMEOUT = "network_timeout"
    DATA_CORRUPTION = "data_corruption"
    FILE_IO_ERROR = "file_io_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    AUTHENTICATION_ERROR = "authentication_error"
    DATABASE_ERROR = "database_error"
    UNKNOWN = "unknown"

class ErrorSeverity(Enum):
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"

class ErrorAction(Enum):
    RETRY = "retry"
    FALLBACK = "fallback"
    CLEANUP_AND_RETRY = "cleanup_and_retry"
    FATAL_FAIL = "fatal_fail"

@dataclass
class ClassificationResult:
    category: ErrorCategory
    severity: ErrorSeverity
    action: ErrorAction
    reason: str
    original_exception: BaseException

class ErrorClassifier:
    @staticmethod
    def classify(exc: BaseException) -> ClassificationResult:
        """例外オブジェクトを解析し、カテゴリ、深刻度、リカバリアクションを判定する."""
        try:
            if isinstance(exc, BaseExceptionGroup):
                return ErrorClassifier._classify_exception_group(exc)
                
            try:
                exc_type_name = type(exc).__name__
            except Exception as name_err:
                exc_type_name = "<UnknownException>"
                
            try:
                exc_msg = str(exc)
            except Exception as str_err:
                exc_msg = f"<Failed to stringify exception: {type(str_err).__name__}>"
            
            exc_msg_lower = exc_msg.lower()
            
            # 1. カテゴリの特定
            category = ErrorCategory.UNKNOWN
            reason = f"Unhandled exception: {exc_type_name}"
            
            # 認証エラーの判定
            if exc_type_name in ("AuthError", "AuthenticationError", "PermissionDenied") or any(x in exc_msg_lower for x in ("unauthorized", "api key", "invalid key", "auth", "credentials", "token expired", "forbidden", "401", "403")):
                category = ErrorCategory.AUTHENTICATION_ERROR
                reason = f"Detected authentication/permission issue in {exc_type_name}: {exc_msg}"

            # API制限の判定
            elif "429" in exc_msg or any(x in exc_msg_lower for x in ("rate limit", "too many requests", "quota exceeded")):
                category = ErrorCategory.API_RATE_LIMIT
                reason = f"Detected API rate limit/quota issue in {exc_type_name}: {exc_msg}"
                
            # タイムアウト・ネットワークエラーの判定
            elif exc_type_name in (
                "TimeoutError", "ConnectTimeout", "ReadTimeout", "ConnectionError", 
                "ConnectionRefusedError", "ConnectionAbortedError", "ConnectionResetError",
                "gaierror", "herror", "SSLError", "SSLEOFError", "SSLCertVerificationError",
                "NewConnectionError", "MaxRetryError", "HTTPError", "URLError"
            ) or any(x in exc_msg_lower for x in (
                "timeout", "timed out", "connection failed", "connection refused", 
                "connection reset", "getaddrinfo failed", "name or service not known", 
                "ssl validation failed", "ssl handshake", "failed to establish a new connection"
            )):
                category = ErrorCategory.NETWORK_TIMEOUT
                reason = f"Detected network/operation timeout in {exc_type_name}: {exc_msg}"
                
            # JSON/データ不整合の判定
            elif exc_type_name == "JSONDecodeError" or isinstance(exc, json.JSONDecodeError) or ("json" in exc_msg_lower and "parse" in exc_msg_lower):
                category = ErrorCategory.DATA_CORRUPTION
                reason = f"Detected data corruption/JSON decode failure in {exc_type_name}: {exc_msg}"
                
            # リソース枯渇の判定
            elif exc_type_name in ("MemoryError", "DiskError") or any(x in exc_msg_lower for x in ("no space left", "out of memory", "disk full", "oom")):
                category = ErrorCategory.RESOURCE_EXHAUSTED
                reason = f"Detected system resource exhaustion in {exc_type_name}: {exc_msg}"

            # データベースエラーの判定
            elif exc_type_name in ("OperationalError", "DatabaseError", "IntegrityError") or any(x in exc_msg_lower for x in ("database", "db connection", "sqlite", "postgresql", "mysql", "cursor")):
                category = ErrorCategory.DATABASE_ERROR
                reason = f"Detected database operation failure in {exc_type_name}: {exc_msg}"

            # ファイルIOエラーの判定 (リソース枯渇等は除外される)
            elif isinstance(exc, OSError) or exc_type_name in ("OSError", "IOError", "PermissionError", "FileNotFoundError") or "permission denied" in exc_msg_lower:
                category = ErrorCategory.FILE_IO_ERROR
                reason = f"Detected file system or IO error in {exc_type_name}: {exc_msg}"
                
            # 2. カテゴリに基づく深刻度とアクションのマッピング
            if category == ErrorCategory.AUTHENTICATION_ERROR:
                severity = ErrorSeverity.CRITICAL
                action = ErrorAction.FATAL_FAIL
            elif category == ErrorCategory.API_RATE_LIMIT:
                severity = ErrorSeverity.MAJOR
                action = ErrorAction.RETRY
            elif category == ErrorCategory.NETWORK_TIMEOUT:
                severity = ErrorSeverity.MAJOR
                action = ErrorAction.RETRY
            elif category == ErrorCategory.DATA_CORRUPTION:
                severity = ErrorSeverity.MODERATE
                action = ErrorAction.FALLBACK
            elif category == ErrorCategory.RESOURCE_EXHAUSTED:
                severity = ErrorSeverity.CRITICAL
                action = ErrorAction.CLEANUP_AND_RETRY
            elif category == ErrorCategory.DATABASE_ERROR:
                severity = ErrorSeverity.MAJOR
                action = ErrorAction.RETRY
            elif category == ErrorCategory.FILE_IO_ERROR:
                severity = ErrorSeverity.MAJOR
                action = ErrorAction.CLEANUP_AND_RETRY
            else:
                severity = ErrorSeverity.CRITICAL
                action = ErrorAction.FATAL_FAIL
                
            return ClassificationResult(
                category=category,
                severity=severity,
                action=action,
                reason=reason,
                original_exception=exc
            )
        except Exception as internal_err:
            # 万が一分類処理自体で例外が発生した場合は、安全にフォールバック結果を返す
            return ClassificationResult(
                category=ErrorCategory.UNKNOWN,
                severity=ErrorSeverity.CRITICAL,
                action=ErrorAction.FATAL_FAIL,
                reason=f"ErrorClassifier internal failure: {type(internal_err).__name__}",
                original_exception=exc
            )

    @staticmethod
    def _classify_exception_group(group: BaseExceptionGroup) -> ClassificationResult:
        # グループ内の例外を再帰的に平坦化
        flat_exceptions = []
        def flatten(e: BaseException):
            if isinstance(e, BaseExceptionGroup):
                for sub_e in e.exceptions:
                    flatten(sub_e)
            else:
                flat_exceptions.append(e)
        flatten(group)
        
        if not flat_exceptions:
            return ClassificationResult(
                category=ErrorCategory.UNKNOWN,
                severity=ErrorSeverity.CRITICAL,
                action=ErrorAction.FATAL_FAIL,
                reason=f"Empty ExceptionGroup: {type(group).__name__}",
                original_exception=group
            )
            
        results = [ErrorClassifier.classify(e) for e in flat_exceptions]
        
        severity_priority = {
            ErrorSeverity.CRITICAL: 4,
            ErrorSeverity.MAJOR: 3,
            ErrorSeverity.MODERATE: 2,
            ErrorSeverity.MINOR: 1
        }
        
        action_priority = {
            ErrorAction.FATAL_FAIL: 4,
            ErrorAction.CLEANUP_AND_RETRY: 3,
            ErrorAction.RETRY: 2,
            ErrorAction.FALLBACK: 1
        }
        
        best_result = results[0]
        best_sev_val = severity_priority.get(best_result.severity, 0)
        best_act_val = action_priority.get(best_result.action, 0)
        
        for r in results[1:]:
            sev_val = severity_priority.get(r.severity, 0)
            act_val = action_priority.get(r.action, 0)
            if sev_val > best_sev_val:
                best_result = r
                best_sev_val = sev_val
                best_act_val = act_val
            elif sev_val == best_sev_val and act_val > best_act_val:
                best_result = r
                best_act_val = act_val
                
        return ClassificationResult(
            category=best_result.category,
            severity=best_result.severity,
            action=best_result.action,
            reason=f"ExceptionGroup contains {best_result.category.value} failure: {best_result.reason}",
            original_exception=group
        )

