import logging
import random
import os
import math
import zlib
import asyncio
from typing import Dict, Any, Union
from datetime import datetime, timedelta

try:
    from googleapiclient.errors import HttpError
except ImportError:
    class HttpError(Exception):
        """googleapiclient がインストールされていない場合のダミー例外クラス"""
        pass

logger = logging.getLogger(__name__)

# MK-01: モック/本番切替フラグ
# YOUTUBE_API_MODE=real で YouTube Analytics API を使用（要 OAuth 設定）
# YOUTUBE_API_MODE=mock（デフォルト）でモックデータを返す
YOUTUBE_API_MODE = os.getenv("YOUTUBE_API_MODE", "mock").lower()

ALL_POINTS = ["01:24", "04:15"]

class PostPublishCollectorError(Exception):
    """PostPublishCollectorに関するエラーの基本例外クラス"""
    pass

class PostPublishCollectorAPIError(PostPublishCollectorError):
    """YouTube Analytics APIへのアクセスや応答取得でエラーが発生した際のエラー"""
    pass

class PostPublishCollectorAuthError(PostPublishCollectorError):
    """API認証失敗や権限不足時のエラー"""
    pass

class PostPublishCollectorQuotaError(PostPublishCollectorError):
    """APIクォータ超過時のエラー"""
    pass

class PostPublishCollectorNotFoundError(PostPublishCollectorError):
    """対象の動画やリソースが見つからなかった時のエラー"""
    pass

class PostPublishCollectorNetworkError(PostPublishCollectorError):
    """APIリクエストのタイムアウトやネットワーク障害時のエラー"""
    pass

class PostPublishCollectorValueError(PostPublishCollectorError, ValueError):
    """無効な値が指定された際のエラー"""
    pass

class PostPublishCollectorTypeError(PostPublishCollectorError, TypeError):
    """無効な型が指定された際のエラー"""
    pass

class PostPublishCollectorNotImplementedError(PostPublishCollectorError, NotImplementedError):
    """未実装の機能が呼び出された際のエラー"""
    pass

PROGRAM_ERRORS = (
    NameError,
    AttributeError,
    AssertionError,
)

class PostPublishCollector:
    """
    [Phase 2.1: Performance Collector]
    動画公開後（24h, 72h, 7d）にYouTube Analytics APIからデータを自動で収集する。
    YOUTUBE_API_MODE=mock 時はseed固定の決定論的ダミーデータを返す。
    """
    
    def __init__(self):
        self._api_mode_override = None

    @property
    def api_mode(self) -> str:
        """動的に環境変数またはグローバル変数をチェックし、バリデーションを行う"""
        if self._api_mode_override is not None:
            return self._api_mode_override
        mode = os.environ.get("YOUTUBE_API_MODE")
        if mode is None:
            mode = YOUTUBE_API_MODE
        else:
            if not isinstance(mode, str):
                raise PostPublishCollectorTypeError("YOUTUBE_API_MODE must be a string")
            mode = mode.lower()
        if not isinstance(mode, str):
            raise PostPublishCollectorTypeError("YOUTUBE_API_MODE must be a string")
        if mode not in ("real", "mock"):
            raise PostPublishCollectorValueError(f"Invalid YOUTUBE_API_MODE: '{mode}'. Must be 'real' or 'mock'.")
        return mode

    @api_mode.setter
    def api_mode(self, value: str):
        if value is not None:
            if not isinstance(value, str):
                raise PostPublishCollectorTypeError("YOUTUBE_API_MODE must be a string or None")
            value = value.lower()
            if value not in ("real", "mock"):
                raise PostPublishCollectorValueError(f"Invalid YOUTUBE_API_MODE: '{value}'. Must be 'real' or 'mock'.")
        self._api_mode_override = value
        
    async def collect_performance_data(self, video_id: str, elapsed_hours: Union[int, float] = 24) -> Dict[str, Any]:
        """
        指定された動画のパフォーマンス指標を取得する
        
        Args:
            video_id: YouTubeのVideo ID
            elapsed_hours: 公開からの経過時間（24, 72, 168等）
        """
        if video_id is None:
            raise PostPublishCollectorValueError("video_id cannot be None")
        if not isinstance(video_id, str):
            raise PostPublishCollectorTypeError("video_id must be a string")
        if not video_id.strip():
            raise PostPublishCollectorValueError("video_id cannot be empty or whitespace only")
        if len(video_id) > 128:
            raise PostPublishCollectorValueError("video_id cannot exceed 128 characters")

        if elapsed_hours is None:
            elapsed_hours = 24
        
        # bool 型は int のサブクラスなので個別に除外
        if isinstance(elapsed_hours, bool):
            raise PostPublishCollectorTypeError("elapsed_hours cannot be a boolean")
            
        if not isinstance(elapsed_hours, (int, float)):
            raise PostPublishCollectorTypeError("elapsed_hours must be a number")
            
        if isinstance(elapsed_hours, float):
            if math.isnan(elapsed_hours):
                raise PostPublishCollectorValueError("elapsed_hours cannot be NaN")
            if math.isinf(elapsed_hours):
                raise PostPublishCollectorValueError("elapsed_hours cannot be Infinity")
            if not elapsed_hours.is_integer():
                raise PostPublishCollectorValueError("elapsed_hours must be a whole number")
            elapsed_hours = int(elapsed_hours)

        if elapsed_hours < 0:
            raise PostPublishCollectorValueError("elapsed_hours must be non-negative")

        try:
            if self.api_mode == "real":
                logger.info(f"📊 [Performance Collector] REAL MODE: Fetching metrics for {video_id}")
                # TODO: YouTube Analytics API 統合
                # googleapiclient.discovery + google-auth で実装予定
                raise NotImplementedError("YouTube Analytics API の本番統合は未実装です。YOUTUBE_API_MODE=mock に設定してください。")

            logger.info(f"📊 [Performance Collector] MOCK MODE: Generating deterministic metrics for {video_id} ({elapsed_hours}h)")
            return self._generate_mock_data(video_id, elapsed_hours)
        except PostPublishCollectorError:
            raise
        except NotImplementedError as e:
            exc = PostPublishCollectorNotImplementedError(str(e))
            exc.__cause__ = e
            raise exc
        except ValueError as e:
            logger.error(f"Validation value error while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            raise PostPublishCollectorValueError(f"Failed to collect performance data: {e}") from e
        except TypeError as e:
            logger.error(f"Validation type error while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            raise PostPublishCollectorTypeError(f"Failed to collect performance data: {e}") from e
        except OverflowError as e:
            logger.error(f"Overflow error while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            raise PostPublishCollectorError(f"Overflow during performance data collection: {e}") from e
        except (OSError, asyncio.TimeoutError) as e:
            logger.error(f"Network or I/O error while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            raise PostPublishCollectorNetworkError(f"Network or I/O failure while collecting performance data: {e}") from e
        except HttpError as e:
            status_code = None
            resp = getattr(e, "resp", None)
            if resp is not None:
                status_code = getattr(resp, "status", None)
            if status_code is None:
                status_code = getattr(e, "status_code", None)
            
            try:
                if status_code is not None:
                    status_code = int(status_code)
            except (ValueError, TypeError):
                pass

            logger.error(f"YouTube Analytics API HTTP error {status_code} while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            
            if status_code in (401, 403):
                err_msg = str(e)
                if "quota" in err_msg.lower() or "limit" in err_msg.lower():
                    raise PostPublishCollectorQuotaError(f"YouTube API quota exceeded or limit reached: {e}") from e
                raise PostPublishCollectorAuthError(f"YouTube API authentication or permission failed: {e}") from e
            elif status_code == 404:
                raise PostPublishCollectorNotFoundError(f"YouTube video or resource not found: {video_id}") from e
            else:
                raise PostPublishCollectorAPIError(f"YouTube API returned HTTP error: {e}") from e
        except Exception as e:
            if isinstance(e, PROGRAM_ERRORS):
                raise
            logger.error(f"Unexpected error while collecting performance data for video_id={video_id}, elapsed_hours={elapsed_hours}: {e}", exc_info=True)
            raise PostPublishCollectorError(f"Unexpected error during performance data collection: {e}") from e



    def _generate_seed(self, video_id: str, elapsed_hours: int) -> int:
        """video_id と経過時間から再現可能なハッシュシードを生成する"""
        if video_id is None:
            raise PostPublishCollectorValueError("video_id cannot be None")
        if not isinstance(video_id, str):
            raise PostPublishCollectorTypeError("video_id must be a string")
        if elapsed_hours is None:
            raise PostPublishCollectorValueError("elapsed_hours cannot be None")
        if isinstance(elapsed_hours, bool):
            raise PostPublishCollectorTypeError("elapsed_hours cannot be a boolean")
        if not isinstance(elapsed_hours, (int, float)):
            raise PostPublishCollectorTypeError("elapsed_hours must be a number")

        # float型の整数値を一貫した文字列表現にするためにintキャスト
        if isinstance(elapsed_hours, float) and elapsed_hours.is_integer():
            elapsed_hours = int(elapsed_hours)

        try:
            return zlib.adler32(f"{video_id}_{elapsed_hours}".encode("utf-8")) % (2**32)
        except (zlib.error, UnicodeEncodeError, TypeError, ValueError, AttributeError) as e:
            # 決定論的なフォールバックハッシュ（Polynomial rolling hash）
            logger.warning("zlib adler32 seed generation failed, falling back to rolling hash. Error: %s", e)
            h = 0
            for char in f"{video_id}_{elapsed_hours}":
                h = (31 * h + ord(char)) % (2**32)
            return h

    def _build_metrics(self, base_views: int, base_ctr: float, base_retention: float) -> Dict[str, Any]:
        """基本指標から詳細なメトリクス辞書を構築する"""
        if base_views is None:
            raise PostPublishCollectorValueError("base_views cannot be None")
        if isinstance(base_views, bool):
            raise PostPublishCollectorTypeError("base_views cannot be a boolean")
        if not isinstance(base_views, (int, float)):
            raise PostPublishCollectorTypeError("base_views must be a number")
        if isinstance(base_views, float):
            if math.isnan(base_views):
                raise PostPublishCollectorValueError("base_views cannot be NaN")
            if math.isinf(base_views):
                raise PostPublishCollectorValueError("base_views cannot be Infinity")

        if base_ctr is None:
            raise PostPublishCollectorValueError("base_ctr cannot be None")
        if isinstance(base_ctr, bool):
            raise PostPublishCollectorTypeError("base_ctr cannot be a boolean")
        if not isinstance(base_ctr, (int, float)):
            raise PostPublishCollectorTypeError("base_ctr must be a number")
        if isinstance(base_ctr, float):
            if math.isnan(base_ctr):
                raise PostPublishCollectorValueError("base_ctr cannot be NaN")
            if math.isinf(base_ctr):
                raise PostPublishCollectorValueError("base_ctr cannot be Infinity")

        if base_retention is None:
            raise PostPublishCollectorValueError("base_retention cannot be None")
        if isinstance(base_retention, bool):
            raise PostPublishCollectorTypeError("base_retention cannot be a boolean")
        if not isinstance(base_retention, (int, float)):
            raise PostPublishCollectorTypeError("base_retention must be a number")
        if isinstance(base_retention, float):
            if math.isnan(base_retention):
                raise PostPublishCollectorValueError("base_retention cannot be NaN")
            if math.isinf(base_retention):
                raise PostPublishCollectorValueError("base_retention cannot be Infinity")

        views = max(0, int(base_views))
        ctr = max(0.0, float(base_ctr))
        retention = max(0.0, float(base_retention))

        # CTRが極端に小さい場合は impressions 計算のオーバーフローを防ぐため 0 とする
        if ctr >= 0.01:
            try:
                impressions = int(views / (ctr / 100))
            except (OverflowError, ZeroDivisionError):
                impressions = 0
        else:
            impressions = 0

        return {
            "views": views,
            "impressions": impressions,
            "click_through_rate": ctr,
            "average_view_duration_seconds": int(600 * (retention / 100)),
            "retention_rate_pct": retention,
            "likes": views * 5 // 100,
            "comments": views * 5 // 1000
        }

    def _build_retention_map(self, base_retention: float, max_duration_seconds: int = 600) -> Dict[str, Any]:
        """基本維持率からリテンションマップ辞書を構築する"""
        if base_retention is None:
            raise PostPublishCollectorValueError("base_retention cannot be None")
        if isinstance(base_retention, bool):
            raise PostPublishCollectorTypeError("base_retention cannot be a boolean")
        if not isinstance(base_retention, (int, float)):
            raise PostPublishCollectorTypeError("base_retention must be a number")
        if isinstance(base_retention, float):
            if math.isnan(base_retention):
                raise PostPublishCollectorValueError("base_retention cannot be NaN")
            if math.isinf(base_retention):
                raise PostPublishCollectorValueError("base_retention cannot be Infinity")

        if max_duration_seconds is None:
            raise PostPublishCollectorValueError("max_duration_seconds cannot be None")
        if isinstance(max_duration_seconds, bool):
            raise PostPublishCollectorTypeError("max_duration_seconds cannot be a boolean")
        if not isinstance(max_duration_seconds, (int, float)):
            raise PostPublishCollectorTypeError("max_duration_seconds must be a number")
        if isinstance(max_duration_seconds, float):
            if math.isnan(max_duration_seconds):
                raise PostPublishCollectorValueError("max_duration_seconds cannot be NaN")
            if math.isinf(max_duration_seconds):
                raise PostPublishCollectorValueError("max_duration_seconds cannot be Infinity")

        all_points = ALL_POINTS
        filtered_points = []
        for pt in all_points:
            try:
                min_str, sec_str = pt.split(":")
                pt_seconds = int(min_str) * 60 + int(sec_str)
                if pt_seconds <= max_duration_seconds:
                    filtered_points.append(pt)
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning("Skipping invalid retention point format '%s': %s", pt, e)

        retention_0_30 = max(0.0, min(100.0, round(float(base_retention) + 20, 1)))
        retention_30_60 = max(0.0, min(100.0, round(float(base_retention) + 10, 1)))
        return {
            "0-30s": retention_0_30,
            "30-60s": retention_30_60,
            "drop_off_points": filtered_points
        }

    def _generate_mock_data(self, video_id: str, elapsed_hours: int) -> Dict[str, Any]:
        """決定論的モックデータを生成（seed固定で再現性を保証）"""
        seed = self._generate_seed(video_id, elapsed_hours)
        rng = random.Random(seed)

        base_views = rng.randint(1000, 50000)
        base_ctr = round(rng.uniform(2.5, 8.5), 1)
        base_retention = round(rng.uniform(35.0, 65.0), 1)
        
        # 決定論的なタイムスタンプ（基準日時 2026-01-01T00:00:00 + elapsed_hours）
        base_time = datetime(2026, 1, 1, 0, 0, 0)
        try:
            mock_time = base_time + timedelta(hours=elapsed_hours)
        except (ValueError, OverflowError, TypeError) as e:
            logger.warning(f"Failed to calculate mock time with elapsed_hours={elapsed_hours}: {e}. Falling back to base_time.")
            mock_time = base_time
        
        metrics = self._build_metrics(base_views, base_ctr, base_retention)
        avg_duration = metrics["average_view_duration_seconds"]

        return {
            "video_id": video_id,
            "metrics_timestamp": mock_time.isoformat(),
            "elapsed_hours": elapsed_hours,
            "is_mock": True,
            "metrics": metrics,
            "retention_map": self._build_retention_map(base_retention, avg_duration)
        }

# Singleton
post_publish_collector = PostPublishCollector()
