import json
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from datetime import datetime, timedelta

from backend.services.youtube_analytics_client import (
    VideoPerformance,
    ChannelPerformance,
    YouTubeAnalyticsClient,
    PERFORMANCE_CACHE,
    CREDENTIALS_PATH,
)

# googleapiclient.errors はテスト実行環境にインストールされていない可能性があるため、
# 必要に応じてモックまたは動的定義を使用します。
try:
    from googleapiclient.errors import HttpError
except ImportError:
    # 存在しない場合のダミー例外クラス
    class HttpError(Exception):
        def __init__(self, resp=None, content=None):
            self.resp = resp or MagicMock()
            self.content = content or b"Error"
            super().__init__("Dummy HttpError")


# ============================================================
# VideoPerformance / ChannelPerformance のテスト
# ============================================================

def test_video_performance_serialization():
    """VideoPerformance のシリアライズとデシリアライズをテスト"""
    vp = VideoPerformance("test_video_123", "Test Title")
    vp.views = 1000
    vp.impressions = 5000
    vp.ctr = 4.5
    vp.avg_view_duration = 150.0
    vp.avg_view_percentage = 45.2
    vp.likes = 50
    vp.comments = 10
    vp.shares = 5
    vp.subscribers_gained = 3
    vp.fetched_at = "2026-05-22T08:00:00"

    d = vp.to_dict()
    assert d["video_id"] == "test_video_123"
    assert d["title"] == "Test Title"
    assert d["views"] == 1000
    assert d["ctr"] == 4.5

    vp2 = VideoPerformance.from_dict(d)
    assert vp2.video_id == "test_video_123"
    assert vp2.title == "Test Title"
    assert vp2.views == 1000
    assert vp2.ctr == 4.5
    assert vp2.avg_view_duration == 150.0
    assert vp2.avg_view_percentage == 45.2
    assert vp2.likes == 50
    assert vp2.comments == 10
    assert vp2.shares == 5
    assert vp2.subscribers_gained == 3
    assert vp2.fetched_at == "2026-05-22T08:00:00"


def test_channel_performance_to_dict():
    """ChannelPerformance の to_dict をテスト"""
    cp = ChannelPerformance()
    cp.avg_ctr = 3.8
    cp.avg_view_duration = 200.0
    cp.avg_view_percentage = 50.0
    cp.total_views = 10000
    cp.total_subscribers = 500
    cp.top_performing_videos = [{"video_id": "v1", "views": 1000}]
    cp.worst_performing_videos = [{"video_id": "v2", "views": 10}]
    cp.ctr_trend = [{"date": "2026-05-22", "ctr": 3.8}]

    d = cp.to_dict()
    assert d["avg_ctr"] == 3.8
    assert d["total_views"] == 10000
    assert d["top_performing_videos"][0]["video_id"] == "v1"


# ============================================================
# YouTubeAnalyticsClient のテスト
# ============================================================

@pytest.fixture
def mock_cache_file(tmp_path):
    """一時ファイルを使用して PERFORMANCE_CACHE パスを上書きするフィクスチャ"""
    cache_path = tmp_path / "performance_cache.json"
    credentials_path = tmp_path / "oauth_credentials.json"
    
    with patch("backend.services.youtube_analytics_client.PERFORMANCE_CACHE", cache_path), \
         patch("backend.services.youtube_analytics_client.CREDENTIALS_PATH", credentials_path):
        yield cache_path, credentials_path


def test_load_cache_success(mock_cache_file):
    """キャッシュファイルが正常に読み込めることを検証"""
    cache_path, _ = mock_cache_file
    cache_data = {
        "videos": {"v1": {"video_id": "v1", "title": "Cached Video"}},
        "channel": {"avg_ctr": 4.2},
        "last_updated": "2026-05-22T08:00:00"
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f)

    client = YouTubeAnalyticsClient()
    assert "v1" in client._cache["videos"]
    assert client._cache["channel"]["avg_ctr"] == 4.2


def test_load_cache_decode_error(mock_cache_file):
    """キャッシュファイルが破損している場合にデフォルトの辞書が返ることを検証"""
    cache_path, _ = mock_cache_file
    # 壊れたJSONの書き込み
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("{invalid_json")

    client = YouTubeAnalyticsClient()
    assert client._cache == {"videos": {}, "channel": {}, "last_updated": ""}


def test_save_cache(mock_cache_file):
    """キャッシュが正しく保存されることを検証"""
    cache_path, _ = mock_cache_file
    client = YouTubeAnalyticsClient()
    client._cache["videos"]["v2"] = {"video_id": "v2", "title": "New Video"}
    client._save_cache()

    assert cache_path.exists()
    with open(cache_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert "v2" in saved_data["videos"]


@pytest.mark.asyncio
async def test_initialize_no_credentials(mock_cache_file):
    """認証情報ファイルが存在しない場合はフォールバックモード（False）になることを検証"""
    _, cred_path = mock_cache_file
    if cred_path.exists():
        cred_path.unlink()

    client = YouTubeAnalyticsClient()
    result = await client.initialize()
    assert result is False
    assert client.is_available is False


@pytest.mark.asyncio
async def test_initialize_success(mock_cache_file):
    """認証情報ファイルが存在し、トークンの有効期限内の場合に正常初期化（True）されることを検証"""
    _, cred_path = mock_cache_file
    cred_data = {
        "token": "test_token",
        "refresh_token": "test_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "scopes": ["scope1"]
    }
    with open(cred_path, "w", encoding="utf-8") as f:
        json.dump(cred_data, f)

    mock_credentials = MagicMock()
    mock_credentials.expired = False
    mock_credentials.to_json.return_value = json.dumps(cred_data)

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_credentials), \
         patch("googleapiclient.discovery.build") as mock_build:
        
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        
        assert result is True
        assert client.is_available is True
        mock_build.assert_any_call("youtube", "v3", credentials=mock_credentials)
        mock_build.assert_any_call("youtubeAnalytics", "v2", credentials=mock_credentials)


@pytest.mark.asyncio
async def test_initialize_token_refresh(mock_cache_file):
    """トークン期限切れの際に自動でリフレッシュされ、新しいトークンが保存されることを検証"""
    _, cred_path = mock_cache_file
    cred_data = {
        "token": "old_token",
        "refresh_token": "test_refresh_token"
    }
    with open(cred_path, "w", encoding="utf-8") as f:
        json.dump(cred_data, f)

    mock_credentials = MagicMock()
    mock_credentials.expired = True
    mock_credentials.refresh_token = "test_refresh_token"
    
    new_cred_data = {"token": "new_token", "refresh_token": "test_refresh_token"}
    mock_credentials.to_json.return_value = json.dumps(new_cred_data)

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_credentials), \
         patch("google.auth.transport.requests.Request") as mock_request, \
         patch("googleapiclient.discovery.build"):
        
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        
        assert result is True
        mock_credentials.refresh.assert_called_once()
        # ファイルに書き戻されたか検証
        with open(cred_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        assert saved_data["token"] == "new_token"


@pytest.mark.asyncio
async def test_initialize_import_error():
    """googleapiclient がインポートできない場合に適切に False を返すことを検証"""
    with patch.dict("sys.modules", {"googleapiclient.discovery": None}):
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        assert result is False


@pytest.mark.asyncio
async def test_initialize_decode_error(mock_cache_file):
    """認証情報ファイルが破損（JSONパースエラー）している場合に適切に例外処理が行われて False を返すことを検証"""
    _, cred_path = mock_cache_file
    with open(cred_path, "w", encoding="utf-8") as f:
        f.write("{corrupt_json")

    with patch("googleapiclient.discovery.build"):
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        assert result is False


@pytest.mark.asyncio
async def test_initialize_runtime_error(mock_cache_file):
    """初期化処理中に RuntimeError が発生した場合に適切に例外処理が行われて False を返すことを検証"""
    _, cred_path = mock_cache_file
    with open(cred_path, "w", encoding="utf-8") as f:
        f.write("{}")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info", side_effect=RuntimeError("Test Runtime Error")):
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        assert result is False


@pytest.mark.asyncio
async def test_get_video_performance_cache_hit():
    """24時間以内のキャッシュが存在する場合に、APIを呼び出さずにキャッシュから返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True  # API利用可能
    
    fetched_time = datetime.now().isoformat()
    client._cache["videos"]["v_cache"] = {
        "video_id": "v_cache",
        "title": "Cache Hit Video",
        "views": 500,
        "fetched_at": fetched_time
    }

    # APIサービスはモックのままで、呼ばれないはず
    client._youtube_service = MagicMock()
    
    result = await client.get_video_performance("v_cache")
    assert result is not None
    assert result.video_id == "v_cache"
    assert result.title == "Cache Hit Video"
    assert result.views == 500
    client._youtube_service.videos.assert_not_called()


@pytest.mark.asyncio
async def test_get_video_performance_fallback_mode():
    """API未接続（is_available == False）の際、キャッシュがあれば返し、なければ None を返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = False
    
    client._cache["videos"]["v_fallback"] = {
        "video_id": "v_fallback",
        "title": "Fallback Video",
        "views": 120
    }

    result1 = await client.get_video_performance("v_fallback")
    assert result1 is not None
    assert result1.title == "Fallback Video"

    result2 = await client.get_video_performance("v_nonexistent")
    assert result2 is None


@pytest.mark.asyncio
async def test_get_video_performance_api_fetch(mock_cache_file):
    """キャッシュがない場合、APIから動画詳細とアナリティクスデータを取得してキャッシュ更新することを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    # YouTube Data API mock response
    mock_yt = MagicMock()
    mock_yt.videos().list().execute.return_value = {
        "items": [{
            "snippet": {"title": "API Video Title"},
            "statistics": {
                "viewCount": "1000",
                "likeCount": "100",
                "commentCount": "10"
            }
        }]
    }
    client._youtube_service = mock_yt

    # YouTube Analytics API mock response
    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {
        "rows": [
            [2000, 0.05, 120.5, 45.0, 15, 8]  # impressions, ctr (0-1), avgDuration, avgPercentage, shares, subs
        ]
    }
    client._analytics_service = mock_analytics

    result = await client.get_video_performance("v_api_new", force_refresh=True)

    assert result is not None
    assert result.video_id == "v_api_new"
    assert result.title == "API Video Title"
    assert result.views == 1000
    assert result.likes == 100
    assert result.comments == 10
    assert result.impressions == 2000
    assert result.ctr == 5.0  # 0.05 * 100
    assert result.avg_view_duration == 120.5
    assert result.avg_view_percentage == 45.0
    assert result.shares == 15
    assert result.subscribers_gained == 8

    # キャッシュに保存されているか確認
    assert "v_api_new" in client._cache["videos"]
    assert client._cache["videos"]["v_api_new"]["views"] == 1000


@pytest.mark.asyncio
async def test_get_video_performance_api_no_item():
    """APIの返却値にアイテムが含まれない場合に None を返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    mock_yt = MagicMock()
    mock_yt.videos().list().execute.return_value = {"items": []}
    client._youtube_service = mock_yt

    result = await client.get_video_performance("v_empty")
    assert result is None


@pytest.mark.asyncio
async def test_get_video_performance_api_error():
    """API呼び出し中に例外（HttpError）が発生した場合に、キャッシュがあればフォールバックし、なければ None を返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    mock_yt = MagicMock()
    # HttpError 例外の発生
    dummy_resp = MagicMock()
    dummy_resp.status = 400
    dummy_content = b"Bad Request"
    mock_yt.videos().list.side_effect = HttpError(dummy_resp, dummy_content)
    client._youtube_service = mock_yt

    # キャッシュなし
    result_no_cache = await client.get_video_performance("v_error_no_cache", force_refresh=True)
    assert result_no_cache is None

    # キャッシュあり
    client._cache["videos"]["v_error_with_cache"] = {
        "video_id": "v_error_with_cache",
        "title": "Cache Rescue Video",
        "views": 333
    }
    result_with_cache = await client.get_video_performance("v_error_with_cache", force_refresh=True)
    assert result_with_cache is not None
    assert result_with_cache.title == "Cache Rescue Video"
    assert result_with_cache.views == 333


@pytest.mark.asyncio
async def test_get_channel_performance_fallback():
    """API未接続時に、キャッシュからチャンネル情報を復元することを検証"""
    client = YouTubeAnalyticsClient()
    client._available = False
    
    client._cache["channel"] = {
        "avg_ctr": 4.5,
        "avg_view_duration": 180.0,
        "avg_view_percentage": 42.0,
        "total_views": 8000
    }

    perf = await client.get_channel_performance()
    assert perf.avg_ctr == 4.5
    assert perf.avg_view_duration == 180.0
    assert perf.avg_view_percentage == 42.0
    assert perf.total_views == 8000


@pytest.mark.asyncio
async def test_get_channel_performance_api(mock_cache_file):
    """APIからチャンネル全体のパフォーマンスを正常に取得してキャッシュ更新することを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {
        "rows": [
            ["2026-05-22", 100, 500, 0.04, 150.0, 40.0, 5],  # day, views, impressions, ctr, duration, pct, subs
            ["2026-05-21", 200, 1000, 0.06, 170.0, 44.0, 10]
        ]
    }
    client._analytics_service = mock_analytics

    perf = await client.get_channel_performance(days=7)

    assert perf.total_views == 300  # 100 + 200
    assert perf.total_subscribers == 15  # 5 + 10
    # 平均の計算: (4.0 + 6.0) / 2 = 5.0
    assert perf.avg_ctr == 5.0
    # 平均 duration: (150.0 + 170.0) / 2 = 160.0
    assert perf.avg_view_duration == 160.0
    # 平均 percentage: (40.0 + 44.0) / 2 = 42.0
    assert perf.avg_view_percentage == 42.0
    assert len(perf.ctr_trend) == 2
    assert perf.ctr_trend[0] == {"date": "2026-05-22", "ctr": 4.0}

    # キャッシュ検証
    assert client._cache["channel"]["total_views"] == 300


@pytest.mark.asyncio
async def test_get_channel_performance_api_empty():
    """APIの返却行が空の場合でも、デフォルトのChannelPerformanceオブジェクトが返ることを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {"rows": []}
    client._analytics_service = mock_analytics

    perf = await client.get_channel_performance()
    assert perf.total_views == 0
    assert perf.avg_ctr == 0.0


@pytest.mark.asyncio
async def test_get_channel_performance_api_error():
    """API呼び出し中にエラーが発生した場合でも、例外がキャッチされてオブジェクトが返ることを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    mock_analytics = MagicMock()
    dummy_resp = MagicMock()
    dummy_resp.status = 400
    dummy_content = b"Bad Request"
    mock_analytics.reports().query.side_effect = HttpError(dummy_resp, dummy_content)
    client._analytics_service = mock_analytics

    perf = await client.get_channel_performance()

    # **落ちた取得を実測 0 として返さない**（R1.5-C4・19周目）。
    # ここは `perf.total_views == 0` を期待していたが、その 0 は
    # 「API が 400 で落ちたのに、再生数を実測 0 回として呼び手に渡す」
    # という捏造そのものだった。0 は本当に取りうる値なので、
    # 受け取った側には「計測していない」と「計測したら 0 だった」の区別が付かない。
    # いまは計測値が None に潰れ、印で理由まで分かる。
    assert perf.total_views is None
    assert perf.avg_ctr is None
    assert perf.total_subscribers is None
    assert perf.top_performing_videos is None
    assert perf.ctr_trend is None

    # 印まで見る。例外はキャッチされてオブジェクト自体は返る（元の検証内容）
    assert perf.is_real is False
    assert perf.data_source == "unavailable"
    assert perf.last_sync is None
    assert "HttpError" in perf.unavailable_reason


def test_get_performance_benchmarks():
    """get_performance_benchmarks の挙動を検証"""
    client = YouTubeAnalyticsClient()
    
    # 1. キャッシュがない（またはデフォルト）のケース
    client._cache = {"videos": {}, "channel": {}, "last_updated": ""}
    benchmarks_default = client.get_performance_benchmarks()
    assert benchmarks_default["source"] == "industry_default"
    assert benchmarks_default["baseline_ctr"] == 3.5

    # 2. キャッシュにデータがあるケース
    client._cache = {
        "videos": {"v1": {}},
        "channel": {
            "avg_ctr": 4.8,
            "avg_view_percentage": 48.5,
            "avg_view_duration": 250.0
        },
        "last_updated": "2026-05-22T08:00:00"
    }
    benchmarks_cached = client.get_performance_benchmarks()
    assert benchmarks_cached["source"] == "analytics_api"
    assert benchmarks_cached["baseline_ctr"] == 4.8
    assert benchmarks_cached["sample_size"] == 1


def test_get_improvement_insights():
    """get_improvement_insights のメッセージ生成ロジックを検証"""
    client = YouTubeAnalyticsClient()

    # 1. デフォルト（未接続）の場合
    client._cache = {"videos": {}, "channel": {}, "last_updated": ""}
    insights_default = client.get_improvement_insights()
    assert "YouTube Analytics API を接続すると" in insights_default[0]

    # 2. 低CTR ＆ 低視聴維持率の場合
    client._cache = {
        "videos": {},
        "channel": {
            "avg_ctr": 2.5,
            "avg_view_percentage": 25.0,
            "avg_view_duration": 100.0
        }
    }
    insights_low = client.get_improvement_insights()
    assert "サムネイルとタイトルの改善が急務" in insights_low[0]
    assert "冒頭フックの強化と構成の見直し" in insights_low[1]

    # 3. 高CTR ＆ 高視聴維持率の場合
    client._cache = {
        "videos": {},
        "channel": {
            "avg_ctr": 6.0,
            "avg_view_percentage": 55.0,
            "avg_view_duration": 300.0
        }
    }
    insights_high = client.get_improvement_insights()
    assert "現在のサムネイル戦略を維持" in insights_high[0]
    assert "コンテンツの質が視聴者に評価" in insights_high[1]

    # 4. 標準的なCTR ＆ 標準的な視聴維持率の場合
    client._cache = {
        "videos": {},
        "channel": {
            "avg_ctr": 4.0,
            "avg_view_percentage": 40.0,
            "avg_view_duration": 200.0
        }
    }
    insights_mid = client.get_improvement_insights()
    assert "タイトルとサムネイルの微調整" in insights_mid[0]
    assert "テンポの改善やハイライト区間" in insights_mid[1]


# ============================================================
# 堅牢化ガード処理の追加テスト
# ============================================================

def test_safe_helpers():
    """_safe_int と _safe_float のフォールバックと型変換を検証"""
    from backend.services.youtube_analytics_client import _safe_int, _safe_float

    # None のケース
    assert _safe_int(None, 10) == 10
    assert _safe_float(None, 5.5) == 5.5

    # 正常変換
    assert _safe_int("123") == 123
    assert _safe_float("123.45") == 123.45

    # floatを表す文字列のint変換
    assert _safe_int("123.45", 9) == 123

    # 不正な文字列（変換不能）
    assert _safe_int("invalid", 9) == 9
    assert _safe_float("invalid", 9.9) == 9.9

    # 不正な型
    assert _safe_int([], 9) == 9
    assert _safe_float([], 9.9) == 9.9


def test_video_performance_from_dict_invalid_type():
    """from_dict が辞書以外を受け取った際のフォールバックを検証"""
    vp = VideoPerformance.from_dict(None)
    assert vp.video_id == "unknown"
    assert vp.views == 0


def test_load_cache_invalid_structure(mock_cache_file):
    """キャッシュデータの構造が不正な場合のフォールバックを検証"""
    cache_path, _ = mock_cache_file
    client = YouTubeAnalyticsClient()

    # 1. キャッシュがリスト形式の場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    cache = client._load_cache()
    assert cache["videos"] == {}
    assert cache["channel"] == {}

    # 2. videos/channel キーが存在しない、または dict ではない場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"videos": "not_a_dict", "channel": []}, f)
    cache = client._load_cache()
    assert cache["videos"] == {}
    assert cache["channel"] == {}

    # 3. last_updated がない場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"videos": {}, "channel": {}}, f)
    cache = client._load_cache()
    assert "last_updated" in cache
    assert cache["last_updated"] == ""


@pytest.mark.asyncio
async def test_get_video_performance_api_invalid_types():
    """APIレスポンスのデータ構造が想定外の型である場合のガード処理を検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    # 1. item が dict ではない場合
    mock_yt = MagicMock()
    mock_yt.videos().list().execute.return_value = {
        "items": ["not_a_dict"]
    }
    client._youtube_service = mock_yt
    res = await client.get_video_performance("v_invalid_item")
    assert res is None

    # 2. statistics が dict ではない場合
    mock_yt2 = MagicMock()
    mock_yt2.videos().list().execute.return_value = {
        "items": [{
            "snippet": {"title": "Title"},
            "statistics": "not_a_dict"
        }]
    }
    client._youtube_service = mock_yt2
    
    # reports.query もモックする必要がある
    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {
        "rows": [[100, 0.05, 120.0, 50.0, 10, 5]]
    }
    client._analytics_service = mock_analytics

    res2 = await client.get_video_performance("v_invalid_stats")
    assert res2 is not None
    assert res2.views == 0  # statsが無いので 0
    assert res2.ctr == 5.0

    # 3. analytics_response が dict ではない場合
    mock_yt3 = MagicMock()
    mock_yt3.videos().list().execute.return_value = {
        "items": [{
            "snippet": {"title": "Title"},
            "statistics": {"viewCount": "10"}
        }]
    }
    client._youtube_service = mock_yt3
    
    mock_analytics2 = MagicMock()
    mock_analytics2.reports().query().execute.return_value = "not_a_dict"
    client._analytics_service = mock_analytics2

    res3 = await client.get_video_performance("v_invalid_analytics")
    assert res3 is not None
    assert res3.views == 10
    assert res3.ctr == 0.0  # analytics_responseが無効なのでデフォルト値


@pytest.mark.asyncio
async def test_get_channel_performance_api_invalid_types():
    """get_channel_performance における型異常レスポンスのガードを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    # 1. response が dict ではない場合
    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = "not_a_dict"
    client._analytics_service = mock_analytics

    perf = await client.get_channel_performance()
    assert perf.total_views == 0

    # 2. rows の列数が不足、または値が None/異常値の混在
    mock_analytics2 = MagicMock()
    mock_analytics2.reports().query().execute.return_value = {
        "rows": [
            ["2026-05-22", "invalid_views", 1000, 0.04, 150.0, 40.0, 5],  # viewsが非数値文字列
            ["2026-05-21", 200, 1000, None, 170.0, 44.0, 10],            # ctrがNone
            ["2026-05-20", 100],                                         # 列数が足りない（長さ2）
            "not_a_list_row"                                             # 行自体が型異常
        ]
    }
    client._analytics_service = mock_analytics2

    perf2 = await client.get_channel_performance(days=7)
    # 有効な行（長さ >= 7）は最初の2行。
    # 最初の行: views="invalid_views" -> 0, impressions=1000, ctr=4.0, duration=150.0, pct=40.0, subs=5
    # 2番目の行: views=200, impressions=1000, ctr=None -> 0.0, duration=170.0, pct=44.0, subs=10
    # 合計 views = 0 + 200 = 200
    # 平均 CTR = (4.0 + 0.0) / 2 = 2.0
    assert perf2.total_views == 200
    assert perf2.avg_ctr == 2.0
    assert perf2.total_subscribers == 15


def test_parse_video_performance_response_edge_cases():
    """_parse_video_performance_response のエッジケース（未カバー行）のテスト"""
    client = YouTubeAnalyticsClient()
    
    # 1. not video_response
    assert client._parse_video_performance_response("v_id", None, {}) is None
    
    # 2. not video_response.get("items")
    assert client._parse_video_performance_response("v_id", {"items": []}, {}) is None
    
    # 3. not isinstance(item, dict)
    assert client._parse_video_performance_response("v_id", {"items": ["not_a_dict"]}, {}) is None
    
    # 4. not isinstance(stats, dict)
    res = client._parse_video_performance_response(
        "v_id", 
        {"items": [{"snippet": {"title": "Title"}, "statistics": "not_a_dict"}]}, 
        {}
    )
    assert res is not None
    assert res.views == 0

    # 5. not isinstance(analytics_response, dict)
    res2 = client._parse_video_performance_response(
        "v_id",
        {"items": [{"snippet": {"title": "Title"}, "statistics": {"viewCount": "10"}}]},
        "not_a_dict"
    )
    assert res2 is not None
    assert res2.views == 10
    assert res2.ctr == 0.0


@pytest.mark.asyncio
async def test_get_video_performance_parse_none():
    """_parse_video_performance_response が None を返した場合に None を返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    mock_yt = MagicMock()
    mock_yt.videos().list().execute.return_value = {"items": [{"snippet": {"title": "Title"}, "statistics": {"viewCount": "10"}}]}
    client._youtube_service = mock_yt
    
    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {"rows": []}
    client._analytics_service = mock_analytics
    
    client._parse_video_performance_response = MagicMock(return_value=None)
    
    res = await client.get_video_performance("v_id")
    assert res is None


@pytest.mark.asyncio
async def test_initialize_token_refresh_async(mock_cache_file):
    """トークン期限切れの際に、_refresh_credentials_if_expired が run_in_executor を介して非同期的に呼び出されることを検証"""
    _, cred_path = mock_cache_file
    cred_data = {
        "token": "old_token",
        "refresh_token": "test_refresh_token"
    }
    with open(cred_path, "w", encoding="utf-8") as f:
        json.dump(cred_data, f)

    mock_credentials = MagicMock()
    mock_credentials.expired = True
    mock_credentials.refresh_token = "test_refresh_token"
    
    new_cred_data = {"token": "new_token", "refresh_token": "test_refresh_token"}
    mock_credentials.to_json.return_value = json.dumps(new_cred_data)

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_credentials), \
         patch("google.auth.transport.requests.Request"), \
         patch("googleapiclient.discovery.build"), \
         patch("asyncio.get_running_loop") as mock_get_loop:
        
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        
        import asyncio
        fut = asyncio.Future()
        fut.set_result(None)
        mock_loop.run_in_executor.return_value = fut
        
        client = YouTubeAnalyticsClient()
        result = await client.initialize()
        
        assert result is True
        mock_get_loop.assert_called_once()
        mock_loop.run_in_executor.assert_called_once_with(
            None,
            client._refresh_credentials_if_expired,
            mock_credentials
        )


# ============================================================
# エッジケース・堅牢性の追加テスト (T-batch_ae20f2-test_weaver-000)
# ============================================================

def test_video_performance_from_dict_extreme_values():
    """VideoPerformance.from_dict に極端な値や異常な型が渡された場合の挙動を検証"""
    # 巨大な整数
    data_huge_int = {
        "video_id": "huge_int",
        "title": "Huge Int Test",
        "views": 10**18,
        "impressions": 10**18,
        "likes": 10**18,
    }
    vp_huge = VideoPerformance.from_dict(data_huge_int)
    assert vp_huge.views == 10**18
    assert vp_huge.impressions == 10**18

    # 巨大な浮動小数点数と負の数
    data_float_edge = {
        "video_id": "float_edge",
        "ctr": 1.79e308,
        "avg_view_duration": -150.0,
        "avg_view_percentage": -45.2,
    }
    vp_float = VideoPerformance.from_dict(data_float_edge)
    assert vp_float.ctr == 1.79e308
    assert vp_float.avg_view_duration == -150.0
    assert vp_float.avg_view_percentage == -45.2

    # None や不正な型（リストや辞書）が渡された場合のデフォルトフォールバック
    data_invalid_types = {
        "video_id": "invalid_types",
        "views": None,
        "impressions": [100],
        "ctr": {"val": 5.5},
        "avg_view_duration": "not_a_number",
        "fetched_at": ["not_a_string"],
    }
    vp_invalid = VideoPerformance.from_dict(data_invalid_types)
    assert vp_invalid.views == 0
    assert vp_invalid.impressions == 0
    assert vp_invalid.ctr == 0.0
    assert vp_invalid.avg_view_duration == 0.0
    assert vp_invalid.fetched_at == "['not_a_string']"  # str() で変換されるため


def test_parse_video_performance_response_malformed_rows():
    """_parse_video_performance_response で APIレスポンスの行データに異常値が含まれる場合の挙動を検証"""
    client = YouTubeAnalyticsClient()
    
    video_response = {
        "items": [{
            "snippet": {"title": "Test Title"},
            "statistics": {"viewCount": "100"}
        }]
    }

    # 1. すべての要素が None の行
    analytics_none_rows = {
        "rows": [[None, None, None, None, None, None]]
    }
    vp_none = client._parse_video_performance_response("v_id", video_response, analytics_none_rows)
    assert vp_none is not None
    assert vp_none.impressions == 0
    assert vp_none.ctr == 0.0
    assert vp_none.avg_view_duration == 0.0
    assert vp_none.avg_view_percentage == 0.0
    assert vp_none.shares == 0
    assert vp_none.subscribers_gained == 0

    # 2. 非数値文字列の行
    analytics_invalid_str = {
        "rows": [["invalid", "invalid", "invalid", "invalid", "invalid", "invalid"]]
    }
    vp_invalid_str = client._parse_video_performance_response("v_id", video_response, analytics_invalid_str)
    assert vp_invalid_str is not None
    assert vp_invalid_str.ctr == 0.0
    assert vp_invalid_str.avg_view_duration == 0.0

    # 3. 行の要素数が不足している場合
    analytics_short_row = {
        "rows": [[1000, 0.05]]  # impressions と ctr のみ
    }
    vp_short = client._parse_video_performance_response("v_id", video_response, analytics_short_row)
    assert vp_short is not None
    assert vp_short.impressions == 1000
    assert vp_short.ctr == 5.0
    assert vp_short.avg_view_duration == 0.0
    assert vp_short.avg_view_percentage == 0.0


@pytest.mark.asyncio
async def test_get_video_performance_unhashable_video_id():
    """get_video_performance に非ハッシュ型（リストなど）の video_id が渡された場合、TypeError が発生することを検証"""
    client = YouTubeAnalyticsClient()
    # 辞書のキーとしてリストは使えないため、TypeError が発生することを確認
    with pytest.raises(TypeError):
        await client.get_video_performance(["unhashable_id"])


@pytest.mark.asyncio
async def test_get_channel_performance_invalid_days_types():
    """get_channel_performance の days 引数に異常な型（None, 文字列, float）が渡された場合、適切に例外処理（または例外送出）されることを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    # 1. days に None が指定された場合 (date.today() - timedelta(days=None) により TypeError が発生することを確認)
    with pytest.raises(TypeError):
        await client.get_channel_performance(days=None)

    # 2. days に非数値文字列が指定された場合 (timedelta(days="seven") により TypeError が発生することを確認)
    with pytest.raises(TypeError):
        await client.get_channel_performance(days="seven")

    # 3. days に float が指定された場合 (timedelta(days=7.5) は動作するが、念のため ChannelPerformance オブジェクトが返ることを確認)
    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {"rows": []}
    client._analytics_service = mock_analytics
    
    perf = await client.get_channel_performance(days=7.5)
    assert isinstance(perf, ChannelPerformance)


# ============================================================
# さらなる極端なエッジケーステスト (T-batch_6c1276-test_weaver-000)
# ============================================================

def test_safe_helpers_extreme_overflow():
    """_safe_int が OverflowError (無限大など) を受け取った際の挙動を検証 (例外が送出されること)"""
    from backend.services.youtube_analytics_client import _safe_int
    with pytest.raises(OverflowError):
        _safe_int(float('inf'))


def test_safe_helpers_nan_and_inf():
    """_safe_float が float('nan') や float('inf') を受け取った際の挙動を検証"""
    from backend.services.youtube_analytics_client import _safe_float
    import math
    assert math.isnan(_safe_float(float('nan')))
    assert _safe_float(float('inf')) == float('inf')


def test_video_performance_from_dict_nested_types():
    """VideoPerformance.from_dict に辞書やリストなどのネストした型が値として渡された場合のガード挙動を検証"""
    data = {
        "video_id": "nested_test",
        "views": {"nested": "dict"},
        "ctr": [1.2, 3.4],
        "avg_view_duration": "120.5",  # 文字列だがfloatに変換可能
    }
    vp = VideoPerformance.from_dict(data)
    assert vp.video_id == "nested_test"
    assert vp.views == 0  # 変換失敗でデフォルト値
    assert vp.ctr == 0.0  # 変換失敗でデフォルト値
    assert vp.avg_view_duration == 120.5  # 正常変換


@pytest.mark.asyncio
async def test_get_video_performance_corrupt_cache_date():
    """キャッシュ内の日付フォーマットが壊れている場合、ValueError が発生することを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    # 壊れた日付フォーマット
    client._cache["videos"]["v_corrupt_date"] = {
        "video_id": "v_corrupt_date",
        "title": "Corrupt Date Video",
        "views": 456,
        "fetched_at": "this-is-not-a-date"
    }

    # ValueError (fromisoformat失敗) が発生することを確認
    with pytest.raises(ValueError):
        await client.get_video_performance("v_corrupt_date")



@pytest.mark.asyncio
async def test_get_channel_performance_non_dict_cache():
    """キャッシュのchannel部分が辞書ではない場合、AttributeError が発生することを検証"""
    client = YouTubeAnalyticsClient()
    client._available = False
    
    # キャッシュを文字列にしておく
    client._cache["channel"] = "not_a_dict"

    with pytest.raises(AttributeError):
        await client.get_channel_performance()


def test_get_performance_benchmarks_non_dict_channel():
    """get_performance_benchmarks で channel が辞書ではない場合、AttributeError が発生することを検証"""
    client = YouTubeAnalyticsClient()
    client._cache = {"videos": {}, "channel": "not_a_dict", "last_updated": ""}
    
    with pytest.raises(AttributeError):
        client.get_performance_benchmarks()


@pytest.mark.asyncio
async def test_get_video_performance_save_cache_os_error(mock_cache_file):
    """キャッシュ保存時に OSError が発生した場合でも例外がキャッチされ、値自体は返されることを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    # APIレスポンス
    mock_yt = MagicMock()
    mock_yt.videos().list().execute.return_value = {
        "items": [{
            "snippet": {"title": "Save Error Test"},
            "statistics": {"viewCount": "999"}
        }]
    }
    client._youtube_service = mock_yt

    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {"rows": []}
    client._analytics_service = mock_analytics

    # _save_cache で OSError を発生させる
    client._save_cache = MagicMock(side_effect=OSError("Disk Full"))

    # キャッシュ書き込みに失敗しても、取得したデータ自体は返るはず
    res = await client.get_video_performance("v_save_err", force_refresh=True)
    assert res is not None
    assert res.title == "Save Error Test"
    assert res.views == 999


def test_load_cache_non_dict_and_non_list(mock_cache_file):
    """キャッシュファイルの中身が辞書でもリストでもない型（数値や文字列、null）の場合のフォールバックを検証"""
    cache_path, _ = mock_cache_file
    client = YouTubeAnalyticsClient()

    # 1. 数値の場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(12345, f)
    cache = client._load_cache()
    assert cache == {"videos": {}, "channel": {}, "last_updated": ""}

    # 2. 文字列の場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump("not_a_json_object", f)
    cache = client._load_cache()
    assert cache == {"videos": {}, "channel": {}, "last_updated": ""}

    # 3. null の場合
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(None, f)
    cache = client._load_cache()
    assert cache == {"videos": {}, "channel": {}, "last_updated": ""}


def test_parse_video_performance_response_rows_not_list():
    """_parse_video_performance_response で rows がリストではなく辞書などである場合の挙動を検証"""
    client = YouTubeAnalyticsClient()
    video_response = {
        "items": [{
            "snippet": {"title": "Title"},
            "statistics": {"viewCount": "100"}
        }]
    }
    analytics_response = {
        "rows": {"not_a_list": "value"}
    }
    vp = client._parse_video_performance_response("v_id", video_response, analytics_response)
    assert vp is not None
    assert vp.views == 100
    assert vp.impressions == 0  # rowsが無効なのでデフォルト値


# ============================================================
# 新たなエッジケーステスト (T-batch_0ff490-test_weaver-001)
# ============================================================

def test_safe_helpers_additional_edges():
    """_safe_int と _safe_float の極端な入力値・不正な型に対する挙動を検証"""
    from backend.services.youtube_analytics_client import _safe_int, _safe_float

    # 空文字列
    assert _safe_int("", -5) == -5
    assert _safe_float("", -5.5) == -5.5

    # 辞書型や object インスタンス
    assert _safe_int({"key": 10}, 42) == 42
    assert _safe_float({"key": 10}, 42.0) == 42.0
    assert _safe_int(object(), 100) == 100
    assert _safe_float(object(), 100.0) == 100.0

    # 非常に長い数値文字列 (Python 3.11+ の int() の制限 4300 桁以下でテスト)
    long_int_str = "9" * 4000
    assert _safe_int(long_int_str, 0) == int(long_int_str)
    
    long_float_str = "9" * 100 + "." + "9" * 100
    assert _safe_float(long_float_str, 0.0) == float(long_float_str)

    # floatを表す文字列 of int 変換 (有効な形式)
    assert _safe_int("12.34", 9) == 12
    # floatを表す文字列 of int 変換 (無効な形式)
    assert _safe_int("12.34.56", 9) == 9


def test_video_performance_from_dict_missing_and_empty():
    """VideoPerformance.from_dict に空の辞書や一部キーが欠損した辞書を渡した場合の挙動を検証"""
    # 完全な空辞書
    vp_empty = VideoPerformance.from_dict({})
    assert vp_empty.video_id == "unknown"
    assert vp_empty.title == ""
    assert vp_empty.views == 0
    assert vp_empty.ctr == 0.0

    # 一部のキーが存在し、一部が欠損している場合
    vp_partial = VideoPerformance.from_dict({
        "video_id": "part_id",
        "views": "150",
    })
    assert vp_partial.video_id == "part_id"
    assert vp_partial.views == 150
    assert vp_partial.impressions == 0
    assert vp_partial.ctr == 0.0


@pytest.mark.asyncio
async def test_load_cache_os_error_handling(mock_cache_file):
    """_load_cache の実行中に OSError (PermissionErrorなど) が発生した場合にデフォルト辞書を返すことを検証"""
    cache_path, _ = mock_cache_file
    client = YouTubeAnalyticsClient()

    # ファイルオープン時に OSError を発生させる
    with patch("builtins.open", side_effect=OSError("Permission Denied")):
        # キャッシュファイルが存在する場合の挙動を模倣するため、exists() を True にモックする
        with patch.object(Path, "exists", return_value=True):
            cache = client._load_cache()
            assert cache == {"videos": {}, "channel": {}, "last_updated": ""}


@pytest.mark.asyncio
async def test_initialize_credentials_value_error(mock_cache_file):
    """Credentials.from_authorized_user_info が ValueError を投げた場合に initialize から伝播することを検証"""
    _, cred_path = mock_cache_file
    with open(cred_path, "w", encoding="utf-8") as f:
        json.dump({"invalid_key": "invalid_val"}, f)

    # from_authorized_user_info が ValueError を投げるようにモックする
    with patch("google.oauth2.credentials.Credentials.from_authorized_user_info", side_effect=ValueError("Invalid credentials format")):
        client = YouTubeAnalyticsClient()
        with pytest.raises(ValueError):
            await client.initialize()


@pytest.mark.asyncio
async def test_get_video_performance_future_cache_date():
    """キャッシュ内の日付が未来（または現在より24時間以内）の場合、キャッシュからデータを返すことを検証"""
    client = YouTubeAnalyticsClient()
    client._available = True
    
    # 未来の日付（24時間以内とみなされる）
    future_time = (datetime.now() + timedelta(hours=12)).isoformat()
    client._cache["videos"]["v_future"] = {
        "video_id": "v_future",
        "title": "Future Cached Video",
        "views": 777,
        "fetched_at": future_time
    }

    client._youtube_service = MagicMock()
    
    result = await client.get_video_performance("v_future")
    assert result is not None
    assert result.views == 777
    client._youtube_service.videos.assert_not_called()


def test_get_improvement_insights_boundary_values():
    """get_improvement_insights における各閾値の境界値での出力を検証"""
    client = YouTubeAnalyticsClient()

    # 1. CTRの境界値: 3.0 ちょうど, 5.0 ちょうど
    # CTR = 3.0
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 3.0, "avg_view_percentage": 40.0}
    }
    insights = client.get_improvement_insights()
    assert "タイトルとサムネイルの微調整" in insights[0]

    # CTR = 5.0
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 5.0, "avg_view_percentage": 40.0}
    }
    insights = client.get_improvement_insights()
    assert "タイトルとサムネイルの微調整" in insights[0]

    # CTR = 2.99
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 2.99, "avg_view_percentage": 40.0}
    }
    insights = client.get_improvement_insights()
    assert "サムネイルとタイトルの改善が急務" in insights[0]

    # CTR = 5.01
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 5.01, "avg_view_percentage": 40.0}
    }
    insights = client.get_improvement_insights()
    assert "現在のサムネイル戦略を維持" in insights[0]

    # 2. 視聴率の境界値: 30.0 ちょうど, 50.0 ちょうど
    # view_percentage = 30.0
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 4.0, "avg_view_percentage": 30.0}
    }
    insights = client.get_improvement_insights()
    assert "テンポの改善やハイライト区間" in insights[1]

    # view_percentage = 50.0
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 4.0, "avg_view_percentage": 50.0}
    }
    insights = client.get_improvement_insights()
    assert "テンポの改善やハイライト区間" in insights[1]

    # view_percentage = 29.9
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 4.0, "avg_view_percentage": 29.9}
    }
    insights = client.get_improvement_insights()
    assert "冒頭フックの強化と構成の見直し" in insights[1]

    # view_percentage = 50.1
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": 4.0, "avg_view_percentage": 50.1}
    }
    insights = client.get_improvement_insights()
    assert "コンテンツの質が視聴者に評価" in insights[1]


@pytest.mark.asyncio
async def test_get_video_performance_analytics_response_short_rows():
    """_parse_video_performance_response で rows 内のリスト要素数が極端に不足している場合の挙動を検証"""
    client = YouTubeAnalyticsClient()
    video_response = {
        "items": [{
            "snippet": {"title": "Title"},
            "statistics": {"viewCount": "100"}
        }]
    }

    # 長さ 0
    res_len_0 = client._parse_video_performance_response("v_id", video_response, {"rows": [[]]})
    assert res_len_0.impressions == 0
    assert res_len_0.ctr == 0.0

    # 長さ 1
    res_len_1 = client._parse_video_performance_response("v_id", video_response, {"rows": [[1000]]})
    assert res_len_1.impressions == 1000
    assert res_len_1.ctr == 0.0

    # 長さ 3
    res_len_3 = client._parse_video_performance_response("v_id", video_response, {"rows": [[1000, 0.05, 120.0]]})
    assert res_len_3.avg_view_duration == 120.0
    assert res_len_3.avg_view_percentage == 0.0

    # 長さ 5
    res_len_5 = client._parse_video_performance_response("v_id", video_response, {"rows": [[1000, 0.05, 120.0, 45.0, 15]]})
    assert res_len_5.shares == 15
    assert res_len_5.subscribers_gained == 0


@pytest.mark.asyncio
async def test_get_channel_performance_negative_days():
    """get_channel_performance に負の日数や 0 が指定された場合の挙動を検証"""
    client = YouTubeAnalyticsClient()
    client._available = True

    mock_analytics = MagicMock()
    mock_analytics.reports().query().execute.return_value = {"rows": []}
    client._analytics_service = mock_analytics

    # days = 0
    perf_0 = await client.get_channel_performance(days=0)
    assert isinstance(perf_0, ChannelPerformance)

    # days = -5
    perf_neg = await client.get_channel_performance(days=-5)
    assert isinstance(perf_neg, ChannelPerformance)


def test_get_performance_benchmarks_invalid_values():
    """get_performance_benchmarks で channel["avg_ctr"] が None や非数値文字列の場合の挙動を検証"""
    client = YouTubeAnalyticsClient()

    # avg_ctr が None の場合、False と評価されて industry_default にフォールバックする
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": None, "avg_view_percentage": 40.0}
    }
    benchmarks_none = client.get_performance_benchmarks()
    assert benchmarks_none["source"] == "industry_default"

    # avg_ctr が非数値文字列の場合、True と評価されてそのまま analytics_api が返る (仕様上の制限)
    client._cache = {
        "videos": {},
        "channel": {"avg_ctr": "invalid_ctr", "avg_view_percentage": 40.0}
    }
    benchmarks_invalid = client.get_performance_benchmarks()
    assert benchmarks_invalid["source"] == "analytics_api"
    assert benchmarks_invalid["baseline_ctr"] == "invalid_ctr"



