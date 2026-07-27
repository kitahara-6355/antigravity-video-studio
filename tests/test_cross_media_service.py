import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.cross_media_service import CrossMediaService

def test_get_default_sns_data():
    service = CrossMediaService()
    data = service.get_default_sns_data()
    
    # 辞書の主要キーが存在することを確認
    assert isinstance(data, dict)
    for platform in ["X", "Instagram", "TikTok", "Threads"]:
        assert platform in data
        assert "followers" in data[platform]
        assert "posts" in data[platform]
        assert isinstance(data[platform]["posts"], list)

def test_analyze_with_default_sns_data():
    service = CrossMediaService()
    youtube_analytics = {
        "publish_time": "2026-05-20T19:00:00",
        "ctr": 6.5
    }
    
    # デフォルトの sns_data (None) で動作検証
    result = service.analyze_cross_media_correlation(youtube_analytics)
    
    assert "platform_contribution" in result
    assert "best_platform" in result["platform_contribution"]
    assert "hashtag_correlation" in result
    assert "optimized_announcement" in result

def test_analyze_publish_time_parse_error():
    service = CrossMediaService()
    
    # publish_time が無効な日付文字列の場合の ValueError
    youtube_analytics_invalid_val = {
        "publish_time": "invalid-date",
        "ctr": 5.0
    }
    # publish_time が無効な型の場合の TypeError (dict型など)
    youtube_analytics_invalid_type = {
        "publish_time": {"date": 2026},
        "ctr": 5.0
    }
    # publish_time が存在しない場合
    youtube_analytics_missing = {
        "ctr": 5.0
    }

    # 各パターンでエラーにならず、現在時刻をフォールバックとして処理することを確認
    for yt_data in [youtube_analytics_invalid_val, youtube_analytics_invalid_type, youtube_analytics_missing]:
        result = service.analyze_cross_media_correlation(yt_data)
        assert "platform_contribution" in result

def test_posted_at_parse_error_and_skip():
    service = CrossMediaService()
    youtube_analytics = {
        "publish_time": "2026-05-20T12:00:00",
        "ctr": 5.0
    }
    
    # posted_at がパースできない投稿を含む SNS データ
    sns_data = {
        "X": {
            "followers": 1000,
            "posts": [
                {
                    "text": "パース失敗 #Python",
                    "impressions": 100,
                    "engagement": 10,
                    "posted_at": "invalid-date" # ValueError
                },
                {
                    "text": "パース失敗型 #Python",
                    "impressions": 100,
                    "engagement": 10,
                    "posted_at": ["2026-05-20T12:00:00"] # TypeError
                },
                {
                    "text": "正常投稿 #Python",
                    "impressions": 100,
                    "engagement": 10,
                    "posted_at": "2026-05-20T12:00:00"
                }
            ]
        }
    }
    
    result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)
    # パース失敗の投稿はスキップされ、正常投稿のみスコア計算される
    # 正常投稿: diff_hours = 0.0, decay = 1.0
    # post_score = 100 * 0.05 + 10 * 1.0 = 15.0
    # contribution = 15.0 * 1.0 = 15.0
    assert result["platform_contribution"]["contribution_scores"]["X"] == 15.0

def test_time_decay_boundary_cases():
    service = CrossMediaService()
    publish_time_str = "2026-05-20T12:00:00"
    
    # 1. 時間差が 0 時間 (decay = 1.0)
    sns_data_0h = {
        "X": {
            "posts": [{
                "text": "テスト",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-20T12:00:00"
            }]
        }
    }
    # 2. 時間差がちょうど 24 時間 (decay = 0.0)
    sns_data_24h = {
        "X": {
            "posts": [{
                "text": "テスト",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-19T12:00:00"
            }]
        }
    }
    # 3. 時間差が 24.1 時間 (対象外のためスコア 0)
    sns_data_over_24h = {
        "X": {
            "posts": [{
                "text": "テスト",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-19T11:54:00" # 24時間と6分
            }]
        }
    }
    
    yt_analytics = {"publish_time": publish_time_str, "ctr": 10.0}
    
    # 0h の場合: スコア = (100*0.05 + 10*1.0) * 1.0 = 15.0
    res_0h = service.analyze_cross_media_correlation(yt_analytics, sns_data_0h)
    assert res_0h["platform_contribution"]["contribution_scores"]["X"] == 15.0
    
    # 24h の場合: スコア = 15.0 * 0.0 = 0.0
    res_24h = service.analyze_cross_media_correlation(yt_analytics, sns_data_24h)
    assert res_24h["platform_contribution"]["contribution_scores"]["X"] == 0.0
    
    # 24.1h の場合: 24時間を超えるため対象外となり、スコア 0.0
    res_over = service.analyze_cross_media_correlation(yt_analytics, sns_data_over_24h)
    assert res_over["platform_contribution"]["contribution_scores"]["X"] == 0.0

def test_hashtag_handling_and_no_hashtags():
    service = CrossMediaService()
    youtube_analytics = {
        "publish_time": "2026-05-20T12:00:00",
        "ctr": 5.0 # ctr_factor = 5.0 / 10.0 = 0.5
    }
    
    # ハッシュタグが重複して含まれる場合
    sns_data_with_tags = {
        "X": {
            "posts": [{
                "text": "同じタグを複数書く #Python #Python #Django",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-20T12:00:00"
            }]
        }
    }
    res_tags = service.analyze_cross_media_correlation(youtube_analytics, sns_data_with_tags)
    # 重複排除されるため #Python のスコアは一回分
    # contribution = (100 * 0.05 + 10 * 1.0) * 1.0 = 15.0
    # tag_score = 15.0 * 0.5 = 7.5
    assert res_tags["hashtag_correlation"]["#Python"] == 7.5
    assert res_tags["hashtag_correlation"]["#Django"] == 7.5
    
    # ハッシュタグが全く存在しない場合のデフォルトハッシュタグ
    sns_data_no_tags = {
        "X": {
            "posts": [{
                "text": "ハッシュタグのないプレーンな投稿です。",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-20T12:00:00"
            }]
        }
    }
    res_no_tags = service.analyze_cross_media_correlation(youtube_analytics, sns_data_no_tags)
    assert res_no_tags["optimized_announcement"]["suggested_hashtags"] == ["#動画編集", "#YouTube", "#自動化"]

def test_default_ctr_value():
    service = CrossMediaService()
    # ctr キーを含まない YouTube アナリティクスデータ
    youtube_analytics = {
        "publish_time": "2026-05-20T12:00:00"
    }
    sns_data = {
        "X": {
            "posts": [{
                "text": "テスト #Tag",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-20T12:00:00"
            }]
        }
    }
    result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)
    # デフォルトの ctr=5.0 が使用され、ctr_factor = 0.5
    # contribution = 15.0
    # tag_score = 15.0 * 0.5 = 7.5
    assert result["hashtag_correlation"]["#Tag"] == 7.5

def test_fallback_announcement_template_and_missing_posts():
    service = CrossMediaService()
    youtube_analytics = {
        "publish_time": "2026-05-20T12:00:00",
        "ctr": 5.0
    }
    
    # posts キーが欠落しているプラットフォーム、および未知のプラットフォームの検証
    sns_data = {
        "UnknownPlatform": { # 未知のプラットフォーム
            "followers": 500,
            "posts": [{
                "text": "未知のテスト #Unknown",
                "impressions": 200,
                "engagement": 20,
                "posted_at": "2026-05-20T12:00:00"
            }]
        },
        "Instagram": {
            "followers": 100,
            # posts キーが存在しない (info.get("posts", []) のフォールバック検証)
        }
    }
    
    result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)
    
    # 1. Instagram の contribution_scores は 0.0 になること
    assert result["platform_contribution"]["contribution_scores"]["Instagram"] == 0.0
    
    # 2. UnknownPlatform の score が最大 (30.0) になるため best_platform となる
    assert result["platform_contribution"]["best_platform"] == "UnknownPlatform"
    
    # 3. 未知のプラットフォームのテンプレートは無いため、X のテンプレートにフォールバックすること
    # X のテンプレート: "【新着動画】YouTubeに新しい動画を公開しました！ぜひご覧ください！ {hashtags} {url}"
    announcement_text = result["optimized_announcement"]["text"]
    assert "【新着動画】" in announcement_text
    assert "https://youtu.be/example" in announcement_text

def test_hashtag_sorting_and_top_three():
    service = CrossMediaService()
    youtube_analytics = {
        "publish_time": "2026-05-20T12:00:00",
        "ctr": 5.0
    }
    sns_data = {
        "X": {
            "posts": [{
                "text": "複数のハッシュタグ #Tag1 #Tag2 #Tag3 #Tag4 #Tag5",
                "impressions": 100,
                "engagement": 10,
                "posted_at": "2026-05-20T12:00:00"
            }]
        }
    }
    # スコアが同じ場合は元の順序や辞書登録順だが、上位3つのみが suggested_hashtags に含まれる
    result = service.analyze_cross_media_correlation(youtube_analytics, sns_data)
    assert len(result["optimized_announcement"]["suggested_hashtags"]) == 3
    for tag in result["optimized_announcement"]["suggested_hashtags"]:
        assert tag in ["#Tag1", "#Tag2", "#Tag3", "#Tag4", "#Tag5"]
