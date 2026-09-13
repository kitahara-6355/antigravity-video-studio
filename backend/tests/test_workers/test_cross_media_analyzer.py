import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from services.cross_media_service import CrossMediaService
from agents.pipeline_types import PipelineContext, Segment
from agents.workers.youtube_opt_worker import YouTubeOptWorker

def test_get_default_sns_data():
    """SNSシミュレーションデータの生成テスト。各プラットフォームのキーが存在し、適切なデータ構造を持つことを検証する。"""
    service = CrossMediaService()
    sns_data = service.get_default_sns_data()

    # 4つの主要プラットフォームが含まれていることを確認
    platforms = ["X", "Instagram", "TikTok", "Threads"]
    for platform in platforms:
        assert platform in sns_data
        data = sns_data[platform]
        assert "followers" in data
        assert isinstance(data["followers"], int)
        assert "posts" in data
        assert isinstance(data["posts"], list)

        # 投稿オブジェクトの構造検証
        for post in data["posts"]:
            assert "text" in post
            assert isinstance(post["text"], str)
            assert "impressions" in post
            assert isinstance(post["impressions"], int)
            assert "engagement" in post
            assert isinstance(post["engagement"], int)
            assert "posted_at" in post
            assert isinstance(post["posted_at"], str)

def test_analyze_cross_media_correlation():
    """相関分析ロジックのテスト。YouTubeのアナリティクスデータとSNSの投稿データを照合し、貢献スコアやハッシュタグ相関、告知テキストが正しく返されることを検証する。"""
    service = CrossMediaService()
    youtube_analytics = {
        "video_id": "vid_001",
        "publish_time": "2026-05-20T19:00:00",
        "views": 2000,
        "ctr": 10.5,
        "retention_rate": 50.0
    }

    result = service.analyze_cross_media_correlation(youtube_analytics)

    # プラットフォーム貢献度分析の確認
    assert "platform_contribution" in result
    assert "best_platform" in result["platform_contribution"]
    assert "contribution_scores" in result["platform_contribution"]
    scores = result["platform_contribution"]["contribution_scores"]
    assert "X" in scores
    assert "Instagram" in scores
    assert "TikTok" in scores
    assert "Threads" in scores

    # ハッシュタグ相関分析の確認
    assert "hashtag_correlation" in result
    assert len(result["hashtag_correlation"]) > 0
    # スコアが数値であることを確認
    for tag, score in result["hashtag_correlation"].items():
        assert isinstance(score, (int, float))

    # 告知最適化テキスト生成の確認
    assert "optimized_announcement" in result
    assert "text" in result["optimized_announcement"]
    assert "suggested_hashtags" in result["optimized_announcement"]
    assert isinstance(result["optimized_announcement"]["suggested_hashtags"], list)
    # 推奨ハッシュタグがハッシュタグ相関分析から選ばれていること
    for tag in result["optimized_announcement"]["suggested_hashtags"]:
        assert tag.startswith("#")

def test_analyze_cross_media_correlation_edge_cases():
    """日時のパース例外、値の欠損、24時間超の除外、スコア計算時のエッジケースをテストする。"""
    from datetime import datetime, timedelta
    service = CrossMediaService()
    
    # 3.1. publish_time や posted_at が不正、または欠損している場合
    youtube_analytics = {
        "video_id": "vid_001",
        "publish_time": "invalid_date", # 不正な日時
        "ctr": 10.5
    }
    
    now_str = datetime.now().isoformat()
    sns_data = {
        "X": {
            "followers": 1000,
            "posts": [
                {
                    "text": "プログラミング #Python",
                    "impressions": 100,
                    "engagement": 10,
                    "posted_at": "invalid_date" # 不正な日時 → スキップされるべき
                },
                {
                    "text": "自動化 #Python",
                    "impressions": 200,
                    "engagement": 20,
                    "posted_at": now_str # 正しい日時 (現在時刻なので、publish_timeのフォールバック値 datetime.now() と24時間以内になる)
                }
            ]
        }
    }
    
    result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)
    assert result["platform_contribution"]["best_platform"] == "X"
    # 不正日時の投稿はスキップされ、正しい日時のみ計算されるはず
    # 24時間以内のためスコア計算されていること
    assert result["platform_contribution"]["contribution_scores"]["X"] > 0

    # 3.2. publish_time キー自体が存在しない場合 (84行目のカバー)
    youtube_analytics_no_pub = {
        "video_id": "vid_002",
        "ctr": 10.5
    }
    result_no_pub = service.analyze_cross_media_correlation(youtube_analytics_no_pub, sns_data)
    assert result_no_pub["platform_contribution"]["contribution_scores"]["X"] > 0

    # 3.3. すべての投稿が24時間超の場合
    youtube_analytics_old = {
        "publish_time": (datetime.now() + timedelta(days=5)).isoformat()
    }
    result_old = service.analyze_cross_media_correlation(youtube_analytics_old, sns_data)
    assert result_old["platform_contribution"]["contribution_scores"]["X"] == 0
    # 推薦タグはデフォルトが適用されること
    assert len(result_old["optimized_announcement"]["suggested_hashtags"]) > 0

    # 3.4. 未知のプラットフォームがbest_platformになる場合 (テンプレートのフォールバックの検証)
    sns_data_unknown = {
        "Facebook": {
            "followers": 5000,
            "posts": [
                {
                    "text": "Facebookでのお知らせ。 #自動化",
                    "impressions": 500,
                    "engagement": 50,
                    "posted_at": now_str
                }
            ]
        }
    }
    result_unknown = service.analyze_cross_media_correlation(youtube_analytics_no_pub, sns_data_unknown)
    assert result_unknown["platform_contribution"]["best_platform"] == "Facebook"
    # Xのテンプレートがフォールバックとして使われるため、告知テキストが含まれていること
    assert "【新着動画】" in result_unknown["optimized_announcement"]["text"]

@pytest.mark.asyncio
async def test_youtube_opt_worker_integration():
    """YouTubeOptWorker.execute() 時に、相関分析結果が ctx.metadata に正しく追加されることをテストする。"""
    
    # パイプラインコンテキストの作成 (引数を修正)
    ctx = PipelineContext(
        video_path="dummy_path.mp4",
        session_id="test_session_999",
        segments=[
            Segment(start=0.0, end=10.0, text="動画自動化の紹介です。")
        ]
    )
    
    # context.metadataを初期化
    ctx.metadata = {}
    
    # YouTubeアナリティクスのダミーをメタデータソースとして設定
    # **SNS の実データを渡す**（R1.5-C4）。渡さないと本線は分析しない
    # （作り物のフォロワー数から投稿先を推奨しないため）。
    # スキップ側の契約は `test_sns_実データが無ければ相関分析しない` にある。
    ctx.metadata_source = {
        "youtube_analytics": {
            "video_id": "vid_999",
            "publish_time": "2026-05-20T19:00:00",
            "views": 5000,
            "ctr": 8.0
        },
        "sns_data": {
            "X": {
                "followers": 320,
                "posts": [
                    {
                        "text": "新しい動画を公開しました #AI #自動化",
                        "impressions": 1200,
                        "engagement": 45,
                        "posted_at": "2026-05-20T19:15:00",
                    }
                ],
            }
        },
    }
    
    # Gemini APIのモック設定
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "titles": ["AIによる動画自動化の未来"],
        "tags": ["AI", "動画", "自動化"],
        "description": "動画の自動化についての解説です。 #AI #自動化",
        "chapters": [{"time": "0:00", "title": "イントロ"}]
    }, ensure_ascii=False)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_factory = MagicMock()
    mock_factory.get_gemini_client.return_value = mock_client
    
    mock_google_genai = MagicMock()
    mock_types = MagicMock()
    mock_google_genai.types = mock_types

    mock_mg = MagicMock()
    mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

    # モックをパッチ
    with patch.dict("sys.modules", {
        "gemini_client_factory": mock_factory,
        "google": MagicMock(),
        "google.genai": mock_google_genai,
        "model_governance": mock_mg,
    }):
        worker = YouTubeOptWorker()
        result = await worker.execute(ctx)
        
        assert result.success is True
        assert "cross_media_correlation" in ctx.metadata
        corr = ctx.metadata["cross_media_correlation"]
        assert "platform_contribution" in corr
        assert "hashtag_correlation" in corr
        assert "optimized_announcement" in corr


@pytest.mark.asyncio
async def test_youtube_opt_worker_api_error_fallback():
    """Gemini APIError 発生時にフォールバック処理に移行することをテストする。"""
    ctx = PipelineContext(
        video_path="dummy_path.mp4",
        session_id="test_session_999",
        segments=[
            Segment(start=0.0, end=10.0, text="動画自動化の紹介です。")
        ]
    )
    ctx.metadata = {}
    
    # ダミーの APIError クラスを定義
    class DummyAPIError(Exception):
        def __init__(self, response_json=None, message=None):
            self.response_json = response_json
            self.message = message
            super().__init__(message or str(response_json))
            
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = DummyAPIError(response_json={"error": "API limit exceeded"})

    mock_factory = MagicMock()
    mock_factory.get_gemini_client.return_value = mock_client
    
    mock_google_genai = MagicMock()
    mock_types = MagicMock()
    mock_google_genai.types = mock_types

    mock_mg = MagicMock()
    mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

    # google.genai.errors モジュールをモックして sys.modules に登録
    import sys
    mock_errors = MagicMock()
    mock_errors.APIError = DummyAPIError

    with patch.dict("sys.modules", {
        "gemini_client_factory": mock_factory,
        "google": MagicMock(),
        "google.genai": mock_google_genai,
        "google.genai.errors": mock_errors,
        "model_governance": mock_mg,
    }):
        worker = YouTubeOptWorker()
        result = await worker.execute(ctx)
        
        assert result.success is True
        assert "フォールバック" in result.detail
        assert "YouTube最適化(Gemini)" in ctx.skipped_features
        assert "titles" in ctx.metadata
        assert len(ctx.metadata["tags"]) >= 5


@pytest.mark.asyncio
async def test_youtube_opt_worker_json_error_fallback():
    """Gemini の返却値が不正な JSON の場合に json.JSONDecodeError でフォールバック処理に移行することをテストする。"""
    ctx = PipelineContext(
        video_path="dummy_path.mp4",
        session_id="test_session_999",
        segments=[
            Segment(start=0.0, end=10.0, text="動画自動化の紹介です。")
        ]
    )
    ctx.metadata = {}
    
    mock_response = MagicMock()
    mock_response.text = "invalid json string"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    mock_factory = MagicMock()
    mock_factory.get_gemini_client.return_value = mock_client
    
    mock_google_genai = MagicMock()
    mock_types = MagicMock()
    mock_google_genai.types = mock_types

    mock_mg = MagicMock()
    mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

    with patch.dict("sys.modules", {
        "gemini_client_factory": mock_factory,
        "google": MagicMock(),
        "google.genai": mock_google_genai,
        "model_governance": mock_mg,
    }):
        worker = YouTubeOptWorker()
        result = await worker.execute(ctx)
        
        assert result.success is True
        assert "フォールバック" in result.detail
        assert "YouTube最適化(Gemini)" in ctx.skipped_features
        assert "titles" in ctx.metadata
        assert len(ctx.metadata["tags"]) >= 5


def test_sns_実データが無ければ相関分析しない():
    """**作り物のフォロワー数から投稿先を推奨しない**（R1.5-C4）。

    `metadata_source["sns_data"]` を入れる経路は本線のどこにも無いので、
    以前はここが**常に** `CrossMediaService.get_default_sns_data()` の作り物
    （X 12,500 フォロワー・Instagram 8,400 …）で相関を取り、
    「最適な投稿先プラットフォーム」と推奨ハッシュタグを `ctx.metadata` に
    埋めていた。収益化の判断に使う数字なので、作り物から出した推奨は嘘になる。

    `retention_analysis` を本線で飛ばしているのと同じ扱いにした。
    台帳: `backend/config/feature_gaps.json` の `sns_cross_media`
    """
    worker = YouTubeOptWorker()
    ctx = PipelineContext(
        video_path="dummy.mp4",
        session_id="test_session_no_sns",
        segments=[],
    )
    ctx.metadata = {}
    ctx.metadata_source = {"youtube_analytics": {"ctr": 8.0}}

    worker._run_cross_media_analysis(ctx)

    assert "cross_media_correlation" not in ctx.metadata, \
        "SNS の実データが無いのに相関分析の結果を成果物へ埋めた"
    assert any("クロスメディア" in s for s in ctx.skipped_features), \
        "飛ばしたことが実行記録に残っていない"


def test_サンプルのSNSデータから出した相関はそう名乗る():
    """`CrossMediaService` を直接呼ぶ経路（デモ・単体テスト）の印（R1.5-C4）。"""
    from services.cross_media_service import CrossMediaService

    service = CrossMediaService()

    作り物 = service.analyze_cross_media_correlation({"ctr": 8.0})
    assert 作り物["is_real"] is False
    assert 作り物["data_source"] == "sample"

    実データ = service.analyze_cross_media_correlation(
        {"ctr": 8.0, "publish_time": "2026-05-20T19:00:00"},
        {"X": {"followers": 320, "posts": [
            {"text": "#AI", "impressions": 1200, "engagement": 45,
             "posted_at": "2026-05-20T19:15:00"}]}},
    )
    assert 実データ["is_real"] is True
    assert 実データ["data_source"] == "measured"
