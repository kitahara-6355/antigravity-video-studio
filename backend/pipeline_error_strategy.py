"""Pipeline Error Propagation Strategy.

4分類のエラーハンドリング戦略を提供する。
- RETRY: 一時的障害 → 自動リトライ（最大3回、exponential backoff）
- FALLBACK: 代替手段あり → フォールバック実行 + 品質低下ログ記録
- FATAL: 復旧不能 → 例外を再送出
- DIAGNOSE: 非クリティカル → ログ記録のみ、処理続行
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

# エラー判定・分類エンジンのインポート
import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from backend.services.error_classifier import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorAction

logger = logging.getLogger(__name__)

# 品質低下ログのデフォルトパス
QUALITY_LOG_PATH = _PROJECT_ROOT / "backend" / "pipeline_quality_log.jsonl"


class PipelineErrorStrategy(Enum):
    """パイプラインエラーの4分類戦略を表すEnum.

    Attributes:
        RETRY: 一時的障害に対するリトライ
        FALLBACK: 代替手段の適用と品質低下記録
        FATAL: 復旧不能なエラーの即時再送出
        DIAGNOSE: 非クリティカルな問題のログ記録と処理続行
    """

    RETRY = "retry"
    FALLBACK = "fallback"
    FATAL = "fatal"
    DIAGNOSE = "diagnose"


class PipelineFatalError(Exception):
    """パイプラインの復旧不可能な重大エラー (FATAL) を示す例外クラス."""
    pass


@dataclass
class QualityDegradation:
    """FALLBACK戦略が適用された際の品質低下記録を表現するデータクラス.

    Attributes:
        phase (str): エラーが発生したパイプラインフェーズ名
        severity (str): 品質低下の重大度 ("minor", "moderate", "major")
        fallback_used (str): 適用されたフォールバック手段の説明
        original_error (str): 発生した元のエラー情報（例外クラス名とメッセージの一部）
        timestamp (str): 記録のタイムスタンプ (ISO 8601 形式、UTC)
    """

    phase: str
    severity: str  # "minor", "moderate", "major"
    fallback_used: str
    original_error: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """データクラスの各属性を辞書(dict)形式に変換して返します。

        Returns:
            dict: 辞書化された品質低下記録データ
        """
        return asdict(self)


def _write_degradation_record(file_path: Path, record: dict) -> None:
    """品質低下レコードをJSONL形式で指定されたファイルパスに追記します。

    Args:
        file_path (Path): 追記対象のファイルパス
        record (dict): 辞書形式 of 品質低下レコード
    """
    os.makedirs(file_path.parent, exist_ok=True)
    with open(file_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log_quality_degradation(degradation: QualityDegradation) -> None:
    """FALLBACK発生時に、品質低下記録を品質ログファイルに記録します。

    書き込み時にOSErrorが発生した場合はログ出力のみを行い、パイプラインの処理自体は妨げません。

    Args:
        degradation (QualityDegradation): 記録する品質低下オブジェクト
    """
    try:
        _write_degradation_record(QUALITY_LOG_PATH, degradation.to_dict())
    except OSError:
        logger.warning("Failed to write quality degradation log")


def _calculate_backoff_seconds(base: float, attempt: int) -> float:
    """指数バックオフ（Exponential Backoff）に基づき、次の試行までの待機秒数を計算します。

    Args:
        base (float): 基底となる秒数
        attempt (int): 現在のリトライ試行回数 (0から始まるインデックス)

    Returns:
        float: 計算された待機秒数
    """
    return base * (2 ** attempt)


def pipeline_retry(operation: Callable, max_retries: int = 3,
                   backoff_base: float = 1.0) -> Any:
    """RETRY戦略: 指定された関数を最大 max_retries 回、指数バックオフを挟んで自動リトライします。

    Args:
        operation (Callable): 実行対象の関数または呼び出し可能オブジェクト。
        max_retries (int, optional): 最大リトライ回数。デフォルトは 3。
        backoff_base (float, optional): バックオフの基底待機秒数。デフォルトは 1.0。

    Returns:
        Any: operation が成功した際の戻り値。

    Raises:
        Exception: max_retries 回試行してもすべて失敗した場合、最後の例外を再送出します。
    """
    last_error = None
    for attempt_index in range(max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_error = e
            if attempt_index < max_retries:
                wait_seconds = _calculate_backoff_seconds(backoff_base, attempt_index)
                logger.warning(
                    "Retry %d/%d for %s: %s (waiting %.1fs)",
                    attempt_index + 1, max_retries,
                    getattr(operation, '__name__', 'unknown'), str(e), wait_seconds
                )
                time.sleep(wait_seconds)
    raise last_error


def pipeline_fallback(phase: str, severity: str, fallback_value: Any,
                      fallback_desc: str) -> Callable:
    """FALLBACK戦略デコレータ: 関数実行エラー時に品質低下ログを記録し、代替値を返します。

    Args:
        phase (str): パイプラインフェーズ名（例: "thumbnail", "srt" など）。
        severity (str): 品質低下の重大度 ("minor", "moderate", "major")。
        fallback_value (Any): 例外発生時に代わりに返却するフォールバック値。
        fallback_desc (str): 適用されたフォールバック処理の説明。

    Returns:
        Callable: デコレートされたラッパー関数。
    """
    def fallback_decorator(operation: Callable) -> Callable:
        @wraps(operation)
        def fallback_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                degradation = QualityDegradation(
                    phase=phase,
                    severity=severity,
                    fallback_used=fallback_desc,
                    original_error=f"{type(e).__name__}: {str(e)[:200]}",
                )
                _log_quality_degradation(degradation)
                logger.warning(
                    "FALLBACK [%s] %s: %s -> %s",
                    phase, severity, str(e)[:100], fallback_desc
                )
                return fallback_value
        return fallback_wrapper
    return fallback_decorator


def pipeline_diagnose(operation: Callable) -> Callable:
    """DIAGNOSE戦略デコレータ: 例外発生時に警告ログ出力のみを行い、Noneを返して処理を続行します。

    Args:
        operation (Callable): 対象の関数。

    Returns:
        Callable: デコレートされたラッパー関数（例外発生時はNoneを返す）。
    """
    @wraps(operation)
    def diagnose_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            logger.warning(
                "DIAGNOSE [%s]: %s (continuing)",
                operation.__name__, str(e)[:200]
            )
            return None
    return diagnose_wrapper


def robust_retry(operation: Callable, max_retries: int = 3, backoff_base: float = 1.0) -> Any:
    """パターン1: API制限/タイムアウト時の動的指数バックオフ & リトライを行います。

    ErrorClassifier によってエラーが API_RATE_LIMIT または NETWORK_TIMEOUT と分類された場合のみ、
    指数バックオフ待機を行って再試行します。それ以外の未サポートのカテゴリのエラーが発生した場合、
    またはリトライ上限に達した場合は、即座に例外を再送出します。

    Args:
        operation (Callable): 実行対象 of 関数または呼び出し可能オブジェクト。
        max_retries (int, optional): 最大リトライ回数。デフォルトは 3。
        backoff_base (float, optional): バックオフの基底待機秒数。デフォルトは 1.0。

    Returns:
        Any: operation が成功した際の戻り値。

    Raises:
        Exception: リトライ上限到達時、またはリトライ対象外のエラーカテゴリの場合、元の例外を発生させます。
    """
    last_error = None
    for attempt_index in range(max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_error = e
            result = ErrorClassifier.classify(e)
            
            # API制限またはタイムアウトのみリトライ対象とする
            if result.category in (ErrorCategory.API_RATE_LIMIT, ErrorCategory.NETWORK_TIMEOUT):
                if attempt_index < max_retries:
                    # API制限の場合は待機時間を2倍にする
                    multiplier = 2.0 if result.category == ErrorCategory.API_RATE_LIMIT else 1.0
                    wait_seconds = _calculate_backoff_seconds(backoff_base, attempt_index) * multiplier
                    logger.warning(
                        "Robust Retry %d/%d for %s (Category: %s): %s (waiting %.1fs)",
                        attempt_index + 1, max_retries,
                        getattr(operation, '__name__', 'unknown'), result.category.value, str(e), wait_seconds
                    )
                    time.sleep(wait_seconds)
                    continue
            # 対象外カテゴリまたはリトライ上限到達時はそのまま例外を発生させる
            raise last_error


def intelligent_fallback(phase: str, severity: str, fallback_value: Any, fallback_desc: str) -> Callable:
    """パターン2: JSON破損/LLM不整合時のプロンプト・パラメーター動的修正 & 再試行デコレータ。

    ErrorClassifier によって DATA_CORRUPTION が検知された場合、呼び出し時の引数 (kwargs) に
    "temperature" もしくは "temp" があれば、自動的に値を 0.0 に変更して一度だけ自己修復的な再試行を行います。
    再試行が失敗した場合、または DATA_CORRUPTION 以外のエラーが発生した場合は、品質低下ログを記録し、
    指定されたフォールバック値を返します。

    Args:
        phase (str): パイプラインフェーズ名。
        severity (str): 品質低下の重大度 ("minor", "moderate", "major")。
        fallback_value (Any): 代替返却値。
        fallback_desc (str): 適用されたフォールバック手段の説明。

    Returns:
        Callable: デコレートされたラッパー関数。
    """
    def fallback_decorator(operation: Callable) -> Callable:
        @wraps(operation)
        def fallback_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                result = ErrorClassifier.classify(e)
                
                # DATA_CORRUPTION の場合はパラメータを調整して一度だけ再試行
                if result.category == ErrorCategory.DATA_CORRUPTION:
                    logger.warning(
                        "DATA_CORRUPTION detected. Attempting self-healing parameter adjustment for %s",
                        operation.__name__
                    )
                    # kwargs に temperature が含まれていれば 0.0 に下げてみる
                    adjusted_kwargs = kwargs.copy()
                    if "temperature" in adjusted_kwargs or "temp" in adjusted_kwargs:
                        for k in ("temperature", "temp"):
                            if k in adjusted_kwargs:
                                adjusted_kwargs[k] = 0.0
                    try:
                        return operation(*args, **adjusted_kwargs)
                    except Exception as sub_e:
                        e = sub_e  # 再試行での例外を記録
                
                # 回復しなかった場合、または対象外カテゴリの場合はフォールバック値を返す
                degradation = QualityDegradation(
                    phase=phase,
                    severity=severity,
                    fallback_used=fallback_desc,
                    original_error=f"{type(e).__name__}: {str(e)[:200]}",
                )
                _log_quality_degradation(degradation)
                logger.warning(
                    "INTELLIGENT_FALLBACK [%s] %s: %s -> %s",
                    phase, severity, str(e)[:100], fallback_desc
                )
                return fallback_value
        return fallback_wrapper
    return fallback_decorator


def healing_io_retry(operation: Callable, max_retries: int = 2) -> Any:
    """パターン3: IO/ディスク容量エラー時のクリーンアップを伴う自動修復 & 再試行を行います。

    FILE_IO_ERROR または RESOURCE_EXHAUSTED を検知した場合、
    ディスククリーンアップスクリプト (`cleanup_disk.main()`) をバックグラウンドで実行し、
    一時ファイルなどを削除した上でリトライします。

    Args:
        operation (Callable): 実行対象 of 関数または呼び出し可能オブジェクト。
        max_retries (int, optional): 最大リトライ回数。デフォルトは 2。

    Returns:
        Any: operation が成功した際の戻り値。

    Raises:
        Exception: クリーンアップ後もリトライに失敗した場合、またはリトライ対象外エラーの場合、元の例外を発生させます。
    """
    last_error = None
    for attempt_index in range(max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_error = e
            result = ErrorClassifier.classify(e)
            
            if result.category in (ErrorCategory.FILE_IO_ERROR, ErrorCategory.RESOURCE_EXHAUSTED):
                if attempt_index < max_retries:
                    logger.warning(
                        "FILE_IO_ERROR or RESOURCE_EXHAUSTED detected. Running disk cleanup before retry %d/%d",
                        attempt_index + 1, max_retries
                    )
                    # ディスククリーンアップの実行
                    try:
                        from backend.agents.orchestration import cleanup_disk
                        cleanup_disk.main()
                    except Exception as cleanup_err:
                        logger.warning("Failed to run disk cleanup: %s", str(cleanup_err))
                    
                    time.sleep(1.0)
                    continue
            raise last_error


