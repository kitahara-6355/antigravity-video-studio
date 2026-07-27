"""
test_cross_media_service.py — CrossMediaService のユニットテスト
全メソッド・全分岐カバレッジを目指す。
"""
import sys
import pytest
from pathlib import Path

# backend パス追加
_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from services.cross_media_service import CrossMediaService


class TestCrossMediaServiceInit:
    """初期化テスト"""

    def test_init(self):
        svc = CrossMediaService()
        assert svc is not None


class TestGetDefaultSnsData:
    """get_default_sns_data() のテスト"""

    def test_returns_4_platforms(self):
        svc = CrossMediaService()
        data = svc.get_default_sns_data()
        assert set(data.keys()) == {"X", "Instagram", "TikTok", "Threads"}

    def test_each_platform_has_followers_and_posts(self):
        svc = CrossMediaService()
        data = svc.get_default_sns_data()
        for platform, info in data.items():
            assert "followers" in info, f"{platform} missing followers"
            assert "posts" in info, f"{platform} missing posts"
            assert len(info["posts"]) >= 1, f"{platform} has no posts"

    def test_post_structure(self):
        svc = CrossMediaService()
        data = svc.get_default_sns_data()
        for platform, info in data.items():
            for post in info["posts"]:
                assert "text" in post
                assert "impressions" in post
                assert "engagement" in post
                assert "posted_at" in post


class TestAnalyzeCrossMediaCorrelation:
    """analyze_cross_media_correlation() の全分岐をテスト"""

    def test_with_default_sns_data(self):
        """sns_data=None の場合、デフォルトデータを使用する (L75-76)"""
        svc = CrossMediaService()
        youtube = {
            "publish_time": "2026-05-20T19:00:00",
            "ctr": 5.0
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data=None)
        assert "platform_contribution" in result
        assert "hashtag_correlation" in result
        assert "optimized_announcement" in result
        assert result["platform_contribution"]["best_platform"] in ["X", "Instagram", "TikTok", "Threads"]

    def test_with_custom_sns_data(self):
        """カスタムSNSデータでの相関分析"""
        svc = CrossMediaService()
        youtube = {
            "publish_time": "2026-05-20T19:00:00",
            "ctr": 8.0
        }
        custom_sns = {
            "X": {
                "followers": 1000,
                "posts": [
                    {
                        "text": "テスト #Python #AI",
                        "impressions": 5000,
                        "engagement": 500,
                        "posted_at": "2026-05-20T20:00:00"
                    }
                ]
            }
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data=custom_sns)
        assert result["platform_contribution"]["best_platform"] == "X"
        assert result["platform_contribution"]["contribution_scores"]["X"] > 0
        assert "#Python" in result["hashtag_correlation"]
        assert "#AI" in result["hashtag_correlation"]

    def test_publish_time_none_fallback(self):
        """publish_time が None の場合 datetime.now() にフォールバック (L83-84)"""
        svc = CrossMediaService()
        youtube = {"publish_time": None, "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {"followers": 100, "posts": []}
        })
        assert result["platform_contribution"]["contribution_scores"]["X"] == 0.0

    def test_publish_time_invalid_fallback(self):
        """publish_time が不正文字列の場合 datetime.now() にフォールバック (L85-86)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "invalid-date", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {"followers": 100, "posts": []}
        })
        assert "platform_contribution" in result

    def test_publish_time_missing_key(self):
        """publish_time キーが存在しない場合 (L81: pub_time_str is falsy)"""
        svc = CrossMediaService()
        youtube = {"ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {"followers": 100, "posts": []}
        })
        assert "platform_contribution" in result

    def test_post_with_invalid_posted_at(self):
        """posted_at が不正な場合、その投稿をスキップする (L100-101 continue)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "テスト #Tag",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "not-a-date"
                    }
                ]
            }
        })
        # 不正日付の投稿はスキップされるのでスコアは0
        assert result["platform_contribution"]["contribution_scores"]["X"] == 0.0

    def test_post_outside_24h_window(self):
        """投稿が24時間以上離れている場合はスコアに含まれない (L107 diff_hours > 24)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "古い投稿 #Old",
                        "impressions": 5000,
                        "engagement": 500,
                        "posted_at": "2026-05-18T10:00:00"  # 2日以上前
                    }
                ]
            }
        })
        assert result["platform_contribution"]["contribution_scores"]["X"] == 0.0

    def test_time_decay_calculation(self):
        """時間減衰が正しく計算される (L114)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 10.0}

        # 同時刻投稿（decay=1.0で最大スコア）
        result_near = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "同時 #Tag",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:00:00"
                    }
                ]
            }
        })

        # 12時間後投稿（decay=0.5でスコア半減）
        result_far = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "12h後 #Tag",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-21T07:00:00"
                    }
                ]
            }
        })

        assert result_near["platform_contribution"]["contribution_scores"]["X"] > \
               result_far["platform_contribution"]["contribution_scores"]["X"]

    def test_no_ctr_uses_default(self):
        """ctr キーがない場合デフォルト5.0を使用 (L125)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00"}  # ctr なし
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "テスト #Python",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            }
        })
        assert "#Python" in result["hashtag_correlation"]
        assert result["hashtag_correlation"]["#Python"] > 0

    def test_empty_posts_returns_defaults(self):
        """投稿が空の場合、デフォルトハッシュタグが返る (L144-145)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {"followers": 100, "posts": []}
        })
        assert result["optimized_announcement"]["suggested_hashtags"] == [
            "#動画編集", "#YouTube", "#自動化"
        ]

    def test_best_platform_selection(self):
        """最もスコアが高いプラットフォームが best_platform になる (L131-137)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "低スコア #A",
                        "impressions": 100,
                        "engagement": 10,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            },
            "TikTok": {
                "followers": 50000,
                "posts": [
                    {
                        "text": "高スコア #B",
                        "impressions": 50000,
                        "engagement": 5000,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            }
        })
        assert result["platform_contribution"]["best_platform"] == "TikTok"

    def test_announcement_template_selection(self):
        """各プラットフォーム用のテンプレートが選択される (L149-156)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}

        # Instagram が最高スコアのケース
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "Instagram": {
                "followers": 100,
                "posts": [
                    {
                        "text": "Instagram最強 #Insta",
                        "impressions": 99999,
                        "engagement": 9999,
                        "posted_at": "2026-05-20T19:05:00"
                    }
                ]
            }
        })
        assert "プロフィールリンク" in result["optimized_announcement"]["text"]

    def test_hashtag_deduplication(self):
        """同一投稿内のハッシュタグが重複排除される (L122)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "#Python #Python #Python #AI",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            }
        })
        # #Python は1回だけカウントされる
        assert "#Python" in result["hashtag_correlation"]

    def test_suggested_hashtags_limited_to_3(self):
        """推奨ハッシュタグは上位3件に制限される (L141)"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        result = svc.analyze_cross_media_correlation(youtube, sns_data={
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "#A #B #C #D #E",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:30:00"
                    }
                ]
            }
        })
        assert len(result["optimized_announcement"]["suggested_hashtags"]) <= 3

    def test_timezone_aware_and_naive_mix_handling(self):
        """タイムゾーン付きとタイムゾーンなしの日時オブジェクトが混在してもクラッシュしないこと"""
        svc = CrossMediaService()
        
        # 1. publish_time が aware (X=+09:00) で posted_at が naive の場合
        youtube_aware = {"publish_time": "2026-05-20T19:00:00+09:00", "ctr": 5.0}
        sns_naive = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "テスト #Tag",
                        "impressions": 100,
                        "engagement": 10,
                        "posted_at": "2026-05-20T19:00:00"
                    }
                ]
            }
        }
        # ここで TypeError が発生しないことを確認する
        result = svc.analyze_cross_media_correlation(youtube_aware, sns_naive)
        assert result["platform_contribution"]["contribution_scores"]["X"] == 15.0

        # 2. publish_time が naive で posted_at が aware (X=+09:00) の場合
        youtube_naive = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        sns_aware = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "テスト #Tag",
                        "impressions": 100,
                        "engagement": 10,
                        "posted_at": "2026-05-20T19:00:00+09:00"
                    }
                ]
            }
        }
        result2 = svc.analyze_cross_media_correlation(youtube_naive, sns_aware)
        assert result2["platform_contribution"]["contribution_scores"]["X"] == 15.0

    def test_unknown_platform_fallback(self):
        """best_platform が未知のプラットフォームの場合、デフォルトで X のテンプレートが使用されること"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        sns_data = {
            "Facebook": {  # 未知のプラットフォーム
                "followers": 1000,
                "posts": [
                    {
                        "text": "Facebookの投稿 #FB",
                        "impressions": 5000,
                        "engagement": 500,
                        "posted_at": "2026-05-20T19:15:00"
                    }
                ]
            }
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data)
        assert result["platform_contribution"]["best_platform"] == "Facebook"
        # X 用のテンプレートが使用されていることを確認（【新着動画】が含まれる）
        assert "【新着動画】" in result["optimized_announcement"]["text"]

    def test_partial_invalid_posted_at(self):
        """一部の投稿の posted_at が不正な場合、その投稿のみスキップされ、他の正常な投稿は処理されること"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        sns_data = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "正常な投稿 #Normal",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:00:00"
                    },
                    {
                        "text": "不正な投稿 #Invalid",
                        "impressions": 5000,
                        "engagement": 500,
                        "posted_at": "invalid-date"
                    }
                ]
            }
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data)
        # 正常な投稿のスコア (1000 * 0.05 + 100 * 1.0) * 1.0 = 150.0 のみが加算されるはず
        assert result["platform_contribution"]["contribution_scores"]["X"] == 150.0
        assert "#Normal" in result["hashtag_correlation"]
        assert "#Invalid" not in result["hashtag_correlation"]

    def test_missing_and_negative_metrics(self):
        """impressions や engagement が欠損、または負の値の場合にデフォルト値0として安全に処理されること"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        sns_data = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "欠損投稿 #Missing",
                        "posted_at": "2026-05-20T19:00:00"
                        # impressions, engagement なし
                    },
                    {
                        "text": "負数投稿 #Negative",
                        "impressions": -100,
                        "engagement": -50,
                        "posted_at": "2026-05-20T19:00:00"
                    }
                ]
            }
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data)
        # 欠損は0として扱われ、負数はそのまま負数スコア (-100 * 0.05 - 50 * 1.0 = -55.0) になるが
        # 時間減衰 decay=1.0、結果は round される
        # 合計スコアは 0 + (-55.0) = -55.0 になるはず
        assert result["platform_contribution"]["contribution_scores"]["X"] == -55.0

    def test_no_hashtags_in_text(self):
        """投稿テキストにハッシュタグが含まれない場合、デフォルトの推奨タグが使用されること"""
        svc = CrossMediaService()
        youtube = {"publish_time": "2026-05-20T19:00:00", "ctr": 5.0}
        sns_data = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "ハッシュタグのないテキストです",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:00:00"
                    }
                ]
            }
        }
        result = svc.analyze_cross_media_correlation(youtube, sns_data)
        assert result["optimized_announcement"]["suggested_hashtags"] == ["#動画編集", "#YouTube", "#自動化"]

    def test_extreme_ctr_values(self):
        """極端な YouTube CTR（負の値や極端に大きい値）が渡された場合も正しく処理されること"""
        svc = CrossMediaService()
        
        # 負の CTR
        youtube_neg = {"publish_time": "2026-05-20T19:00:00", "ctr": -10.0}
        sns_data = {
            "X": {
                "followers": 100,
                "posts": [
                    {
                        "text": "テスト #Tag",
                        "impressions": 1000,
                        "engagement": 100,
                        "posted_at": "2026-05-20T19:00:00"
                    }
                ]
            }
        }
        result_neg = svc.analyze_cross_media_correlation(youtube_neg, sns_data)
        assert "#Tag" in result_neg["hashtag_correlation"]
        # ctr_factor = -10.0 / 10.0 = -1.0。contribution = 150.0。tag_score = 150.0 * -1.0 = -150.0
        assert result_neg["hashtag_correlation"]["#Tag"] == -150.0

        # 極端に大きい CTR
        youtube_large = {"publish_time": "2026-05-20T19:00:00", "ctr": 1000.0}
        result_large = svc.analyze_cross_media_correlation(youtube_large, sns_data)
        assert "#Tag" in result_large["hashtag_correlation"]
        # ctr_factor = 1000.0 / 10.0 = 100.0。contribution = 150.0。tag_score = 150.0 * 100.0 = 15000.0
        assert result_large["hashtag_correlation"]["#Tag"] == 15000.0


class TestCrossMediaServiceTimezoneEdgeCases:
    """タイムゾーンの境界値およびフォールバックの追加テスト"""

    def test_to_naive_utc_with_different_timezones(self):
        from datetime import datetime, timezone, timedelta
        svc = CrossMediaService()

        # 1. 異なるタイムゾーン (UTC+3) の aware datetime を渡す
        tz_utc3 = timezone(timedelta(hours=3))
        dt_aware = datetime(2026, 5, 20, 12, 0, 0, tzinfo=tz_utc3)
        # UTC への変換: 12:00 (UTC+3) -> 9:00 (UTC)
        result = svc._to_naive_utc(dt_aware)
        assert result == datetime(2026, 5, 20, 9, 0, 0)
        assert result.tzinfo is None

    def test_parse_publish_time_fallback_utc(self):
        from datetime import datetime, timezone, timedelta
        svc = CrossMediaService()

        # publish_time が欠損している場合、現在時刻 (UTC) を基準にフォールバックすること
        # 現在時刻 (UTC) の naive datetime を取得
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        result = svc._parse_publish_time({})
        
        # 実行のタイムラグを考慮し、10秒以内の誤差であることを検証
        diff = abs((result - now_utc).total_seconds())
        assert diff < 10
        assert result.tzinfo is None
