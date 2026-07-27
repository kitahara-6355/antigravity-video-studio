"""
YouTube Analytics クライアント — 実績データに基づくフィードバックループ

U-01: YouTube Analytics API統合

機能:
- YouTube Data API v3 によるチャンネル/動画パフォーマンスデータ取得
- CTR・視聴維持率の実績データ蓄積
- パフォーマンスデータを YouTubeOptimizerPlugin のフィードバックに利用
- OAuth2 認証フロー（初回のみ対話的、以降はリフレッシュトークン）

設計方針:
- API キー未設定時は graceful degradation（モック/フォールバック）
- 取得データは JSON で永続化し、TickLoop で定期更新可能
"""

import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ============================================================
# 設定
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "youtube_analytics"
CREDENTIALS_PATH = DATA_DIR / "oauth_credentials.json"
PERFORMANCE_CACHE = DATA_DIR / "performance_cache.json"


# ============================================================
# データ構造
# ============================================================

def _safe_int(val, default: int = 0) -> int:
    """数値を安全に整数に変換する。変換できない場合はデフォルト値を返す"""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default


def _safe_float(val, default: float = 0.0) -> float:
    """数値を安全に浮動小数点数に変換する。変換できない場合はデフォルト値を返す"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class VideoPerformance:
    """個別動画のパフォーマンスデータ"""

    def __init__(self, video_id: str, title: str = ""):
        self.video_id = video_id
        self.title = title
        self.views: int = 0
        self.impressions: int = 0
        self.ctr: float = 0.0  # Click-Through Rate (%)
        self.avg_view_duration: float = 0.0  # 平均視聴時間（秒）
        self.avg_view_percentage: float = 0.0  # 平均視聴率（%）
        self.likes: int = 0
        self.comments: int = 0
        self.shares: int = 0
        self.subscribers_gained: int = 0
        self.fetched_at: str = ""

    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "views": self.views,
            "impressions": self.impressions,
            "ctr": self.ctr,
            "avg_view_duration": self.avg_view_duration,
            "avg_view_percentage": self.avg_view_percentage,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "subscribers_gained": self.subscribers_gained,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "VideoPerformance":
        if not isinstance(data, dict):
            logger.warning("VideoPerformance.from_dict: data is not a dict")
            data = {}
        
        video_id = data.get("video_id", "unknown")
        vp = cls(video_id, data.get("title", ""))
        vp.views = _safe_int(data.get("views", 0))
        vp.impressions = _safe_int(data.get("impressions", 0))
        vp.ctr = _safe_float(data.get("ctr", 0.0))
        vp.avg_view_duration = _safe_float(data.get("avg_view_duration", 0.0))
        vp.avg_view_percentage = _safe_float(data.get("avg_view_percentage", 0.0))
        vp.likes = _safe_int(data.get("likes", 0))
        vp.comments = _safe_int(data.get("comments", 0))
        vp.shares = _safe_int(data.get("shares", 0))
        vp.subscribers_gained = _safe_int(data.get("subscribers_gained", 0))
        vp.fetched_at = str(data.get("fetched_at", ""))
        return vp


class ChannelPerformance:
    """チャンネル全体のパフォーマンスサマリー"""

    def __init__(self):
        self.avg_ctr: float = 0.0
        self.avg_view_duration: float = 0.0
        self.avg_view_percentage: float = 0.0
        self.total_views: int = 0
        self.total_subscribers: int = 0
        self.top_performing_videos: List[Dict] = []
        self.worst_performing_videos: List[Dict] = []
        self.ctr_trend: List[Dict] = []  # 直近30日のCTR推移

    def to_dict(self) -> Dict:
        return {
            "avg_ctr": self.avg_ctr,
            "avg_view_duration": self.avg_view_duration,
            "avg_view_percentage": self.avg_view_percentage,
            "total_views": self.total_views,
            "total_subscribers": self.total_subscribers,
            "top_performing_videos": self.top_performing_videos,
            "worst_performing_videos": self.worst_performing_videos,
            "ctr_trend": self.ctr_trend,
        }


# ============================================================
# メインクライアント
# ============================================================

class YouTubeAnalyticsClient:
    """
    YouTube Analytics API クライアント

    YouTube Data API v3 + YouTube Analytics API を使用して
    チャンネルと動画のパフォーマンスデータを取得する。

    API 未設定時は graceful degradation でキャッシュデータを返す。
    """

    def __init__(self):
        self._youtube_service = None
        self._analytics_service = None
        self._available = False
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict:
        """キャッシュデータを読み込み"""
        default_cache = {"videos": {}, "channel": {}, "last_updated": ""}
        if PERFORMANCE_CACHE.exists():
            try:
                with open(PERFORMANCE_CACHE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    if not isinstance(cache, dict):
                        logger.warning("Cache is not a dictionary. Using default.")
                        return default_cache
                    
                    if "videos" not in cache or not isinstance(cache["videos"], dict):
                        cache["videos"] = {}
                    if "channel" not in cache or not isinstance(cache["channel"], dict):
                        cache["channel"] = {}
                    if "last_updated" not in cache:
                        cache["last_updated"] = ""
                    
                    return cache
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load cache: {e}")
        return default_cache

    def _save_cache(self):
        """キャッシュデータを保存"""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(PERFORMANCE_CACHE, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _load_credentials(self) -> Optional[Any]:
        """OAuth 認証情報をファイルから読み込み、Credentials オブジェクトを構築する"""
        from google.oauth2.credentials import Credentials

        if not CREDENTIALS_PATH.exists():
            logger.info(
                "YouTube Analytics: OAuth credentials not found. "
                "Running in cache/fallback mode."
            )
            return None

        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            cred_data = json.load(f)

        return Credentials.from_authorized_user_info(cred_data)

    def _refresh_credentials_if_expired(self, credentials: Any) -> None:
        """認証情報が期限切れで、かつリフレッシュトークンが存在する場合にリフレッシュして保存する"""
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request
            credentials.refresh(Request())
            # 更新されたトークンを保存
            with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
                json.dump(json.loads(credentials.to_json()), f)

    async def initialize(self) -> bool:
        """
        API サービスを初期化

        Returns:
            True: API利用可能, False: API未設定（フォールバックモード）
        """
        try:
            from googleapiclient.discovery import build

            credentials = self._load_credentials()
            if credentials is None:
                return False

            # トークン更新
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._refresh_credentials_if_expired,
                credentials
            )

            self._youtube_service = build("youtube", "v3", credentials=credentials)
            self._analytics_service = build(
                "youtubeAnalytics", "v2", credentials=credentials
            )
            self._available = True
            logger.info("✅ YouTube Analytics API initialized")
            return True

        except ImportError:
            logger.warning(
                "google-api-python-client not installed. "
                "pip install google-api-python-client google-auth"
            )
            return False
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"YouTube Analytics credentials error: {e}")
            return False
        except RuntimeError as e:
            logger.warning(f"YouTube Analytics runtime error: {e}")
            return False

    @property
    def is_available(self) -> bool:
        return self._available

    # ============================================================
    # 動画パフォーマンスデータ取得
    # ============================================================

    async def _fetch_video_details_from_api(self, video_id: str) -> Optional[Dict[str, Any]]:
        """YouTube Data API を使用して動画の基本情報を非同期で取得する"""
        import asyncio
        loop = asyncio.get_running_loop()
        video_response = await loop.run_in_executor(
            None,
            lambda: self._youtube_service.videos()
            .list(part="snippet,statistics", id=video_id)
            .execute(),
        )
        return video_response

    async def _fetch_video_analytics_from_api(self, video_id: str) -> Optional[Dict[str, Any]]:
        """YouTube Analytics API を使用して動画のCTRや視聴維持率を非同期で取得する"""
        import asyncio
        loop = asyncio.get_running_loop()
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=28)).isoformat()

        analytics_response = await loop.run_in_executor(
            None,
            lambda: self._analytics_service.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="impressions,impressionClickThroughRate,"
                "averageViewDuration,averageViewPercentage,"
                "shares,subscribersGained",
                filters=f"video=={video_id}",
            )
            .execute(),
        )
        return analytics_response

    def _parse_video_performance_response(
        self, video_id: str, video_response: Dict[str, Any], analytics_response: Any
    ) -> Optional[VideoPerformance]:
        """API レスポンスをパースして VideoPerformance オブジェクトを構築する"""
        if not video_response or not video_response.get("items"):
            return None

        item = video_response["items"][0]
        if not isinstance(item, dict):
            return None

        snippet = item.get("snippet", {})
        title = snippet.get("title", "") if isinstance(snippet, dict) else ""
        stats = item.get("statistics", {})
        if not isinstance(stats, dict):
            stats = {}

        vp = VideoPerformance(video_id, title)
        vp.views = _safe_int(stats.get("viewCount", 0))
        vp.likes = _safe_int(stats.get("likeCount", 0))
        vp.comments = _safe_int(stats.get("commentCount", 0))

        if not isinstance(analytics_response, dict):
            analytics_response = {}

        rows = analytics_response.get("rows", [])
        if rows and isinstance(rows, list):
            row = rows[0]
            if isinstance(row, (list, tuple)):
                vp.impressions = _safe_int(row[0]) if len(row) > 0 else 0
                vp.ctr = round(_safe_float(row[1]) * 100, 2) if len(row) > 1 else 0.0
                vp.avg_view_duration = _safe_float(row[2]) if len(row) > 2 else 0.0
                vp.avg_view_percentage = round(_safe_float(row[3]), 1) if len(row) > 3 else 0.0
                vp.shares = _safe_int(row[4]) if len(row) > 4 else 0
                vp.subscribers_gained = _safe_int(row[5]) if len(row) > 5 else 0

        vp.fetched_at = datetime.now().isoformat()
        return vp

    async def get_video_performance(
        self, video_id: str, force_refresh: bool = False
    ) -> Optional[VideoPerformance]:
        """
        個別動画のパフォーマンスデータを取得

        Args:
            video_id: YouTube動画ID
            force_refresh: True の場合キャッシュを無視してAPI取得
        """
        # キャッシュチェック
        if not force_refresh and video_id in self._cache["videos"]:
            cached = self._cache["videos"][video_id]
            cache_age = (
                datetime.now()
                - datetime.fromisoformat(cached.get("fetched_at", "2000-01-01"))
            ).total_seconds()
            if cache_age < 86400:  # 24時間以内
                return VideoPerformance.from_dict(cached)

        if not self._available:
            # フォールバック: キャッシュがあればそれを返す
            if video_id in self._cache["videos"]:
                return VideoPerformance.from_dict(self._cache["videos"][video_id])
            return None

        try:
            from googleapiclient.errors import HttpError

            video_response = await self._fetch_video_details_from_api(video_id)
            if not video_response or not video_response.get("items"):
                return None

            item = video_response["items"][0]
            if not isinstance(item, dict):
                return None

            analytics_response = await self._fetch_video_analytics_from_api(video_id)

            vp = self._parse_video_performance_response(
                video_id, video_response, analytics_response
            )
            if vp is None:
                return None

            # キャッシュに保存
            self._cache["videos"][video_id] = vp.to_dict()
            self._save_cache()

            logger.info(
                f"📊 Video {video_id}: CTR={vp.ctr}%, "
                f"AvgView={vp.avg_view_percentage}%"
            )
            return vp

        except (HttpError, json.JSONDecodeError, KeyError, OSError, ValueError) as e:
            logger.error(f"Failed to fetch video performance: {e}")
            if video_id in self._cache["videos"]:
                return VideoPerformance.from_dict(self._cache["videos"][video_id])
            return None

    # ============================================================
    # チャンネルパフォーマンスサマリー
    # ============================================================

    async def _fetch_channel_analytics_report(self, days: int) -> Optional[Dict[str, Any]]:
        """YouTube Analytics API を使用してチャンネル全体のパフォーマンス統計を非同期で取得する"""
        import asyncio
        loop = asyncio.get_running_loop()
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=days)).isoformat()

        response = await loop.run_in_executor(
            None,
            lambda: self._analytics_service.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,impressions,impressionClickThroughRate,"
                "averageViewDuration,averageViewPercentage,"
                "subscribersGained",
                dimensions="day",
                sort="-day",
            )
            .execute(),
        )
        return response

    def _aggregate_channel_performance(
        self, response: Any, perf: ChannelPerformance
    ) -> None:
        """API レスポンスデータを集計して ChannelPerformance オブジェクトにマッピングする"""
        if not isinstance(response, dict):
            response = {}

        rows = response.get("rows", [])
        if rows and isinstance(rows, list):
            valid_rows = []
            for r in rows:
                if isinstance(r, (list, tuple)) and len(r) >= 7:
                    valid_rows.append(r)

            if valid_rows:
                total_views_calc = sum(_safe_int(r[1]) for r in valid_rows)

                perf.total_views = total_views_calc
                perf.avg_ctr = round(
                    sum(_safe_float(r[3]) for r in valid_rows) / len(valid_rows) * 100, 2
                )
                perf.avg_view_duration = round(
                    sum(_safe_float(r[4]) for r in valid_rows) / len(valid_rows), 1
                )
                perf.avg_view_percentage = round(
                    sum(_safe_float(r[5]) for r in valid_rows) / len(valid_rows), 1
                )
                perf.total_subscribers = sum(_safe_int(r[6]) for r in valid_rows)

                # CTRトレンド
                perf.ctr_trend = []
                for r in valid_rows[:30]:
                    perf.ctr_trend.append({
                        "date": str(r[0]),
                        "ctr": round(_safe_float(r[3]) * 100, 2)
                    })

    async def get_channel_performance(
        self, days: int = 28
    ) -> ChannelPerformance:
        """
        チャンネル全体のパフォーマンスサマリーを取得

        Args:
            days: 集計期間（デフォルト28日）
        """
        perf = ChannelPerformance()

        if not self._available:
            # キャッシュからの復元
            if self._cache.get("channel"):
                cached = self._cache["channel"]
                perf.avg_ctr = cached.get("avg_ctr", 0)
                perf.avg_view_duration = cached.get("avg_view_duration", 0)
                perf.avg_view_percentage = cached.get("avg_view_percentage", 0)
                perf.total_views = cached.get("total_views", 0)
            return perf

        try:
            from googleapiclient.errors import HttpError

            response = await self._fetch_channel_analytics_report(days)
            self._aggregate_channel_performance(response, perf)

            # キャッシュに保存
            self._cache["channel"] = perf.to_dict()
            self._cache["last_updated"] = datetime.now().isoformat()
            self._save_cache()

            logger.info(
                f"📊 Channel: AvgCTR={perf.avg_ctr}%, "
                f"AvgViewPct={perf.avg_view_percentage}%"
            )

        except (HttpError, json.JSONDecodeError, KeyError, OSError, ValueError) as e:
            logger.error(f"Failed to fetch channel performance: {e}")

        return perf

    # ============================================================
    # フィードバックループ連携
    # ============================================================

    def get_performance_benchmarks(self) -> Dict[str, Any]:
        """
        YouTubeOptimizerPlugin に渡すパフォーマンスベンチマーク

        CTR予測の基準値として、実績データを返す。
        API 未接続時はキャッシュまたはデフォルト値。
        """
        channel = self._cache.get("channel", {})
        videos = self._cache.get("videos", {})

        # 実績ベースのベンチマーク
        if channel.get("avg_ctr"):
            return {
                "baseline_ctr": channel["avg_ctr"],
                "baseline_view_pct": channel.get("avg_view_percentage", 0),
                "baseline_view_duration": channel.get("avg_view_duration", 0),
                "sample_size": len(videos),
                "source": "analytics_api",
            }

        # デフォルト（業界平均）
        return {
            "baseline_ctr": 3.5,
            "baseline_view_pct": 40.0,
            "baseline_view_duration": 300.0,
            "sample_size": 0,
            "source": "industry_default",
        }

    def get_improvement_insights(self) -> List[str]:
        """
        実績データに基づく改善インサイトを生成

        YouTubeOptimizerPlugin が次回の最適化に活用。
        """
        insights = []
        benchmarks = self.get_performance_benchmarks()

        if benchmarks["source"] == "industry_default":
            insights.append(
                "YouTube Analytics API を接続すると、"
                "実績データに基づく精密なCTR予測が可能になります"
            )
            return insights

        ctr = benchmarks["baseline_ctr"]
        view_pct = benchmarks["baseline_view_pct"]

        if ctr < 3.0:
            insights.append(
                f"チャンネル平均CTR {ctr}% は業界平均以下。"
                "サムネイルとタイトルの改善が急務です"
            )
        elif ctr > 5.0:
            insights.append(
                f"チャンネル平均CTR {ctr}% は優秀。"
                "現在のサムネイル戦略を維持してください"
            )
        else:
            insights.append(
                f"チャンネル平均CTR {ctr}% は標準的。"
                "タイトルとサムネイルの微調整で向上の余地があります"
            )

        if view_pct < 30.0:
            insights.append(
                f"平均視聴率 {view_pct}% は低め。"
                "冒頭フックの強化と構成の見直しを推奨します"
            )
        elif view_pct > 50.0:
            insights.append(
                f"平均視聴率 {view_pct}% は高水準。"
                "コンテンツの質が視聴者に評価されています"
            )
        else:
            insights.append(
                f"平均視聴率 {view_pct}% は平均的。"
                "テンポの改善やハイライト区間の強調を検討してください"
            )

        return insights


# ============================================================
# シングルトン
# ============================================================
youtube_analytics = YouTubeAnalyticsClient()
