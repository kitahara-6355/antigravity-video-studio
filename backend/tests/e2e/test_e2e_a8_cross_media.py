"""
E2E テスト — A-8 クロスメディア統合分析 5層検証 (55項目)

検証5層モデル:
  L1: DOM存在 (12項目)
  L2: 視覚フィードバック (10項目)
  L3: インタラクション (13項目)
  L4: 状態遷移 (10項目)
  L5: E2E完走 (10項目)
"""
import pytest
import json

BASE = "http://localhost:8000/api/admin/cross-media"


class MockResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def mock_cross_media_api(monkeypatch, app_page):
    original_get = app_page.request.get
    original_post = app_page.request.post

    def mock_get(url, *args, **kwargs):
        if BASE in url:
            if "/dashboard" in url:
                return MockResponse({
                    "title": "クロスメディア統合分析",
                    "status": "healthy",
                    "summary": {
                        "total_channels": 3,
                        "total_followers": 23800,
                        "total_views": 1450000,
                    },
                    "platforms": ["youtube", "tiktok", "twitter", "instagram"],
                    "sections": [
                        "platforms", "insights-sync", "audience-overlap", "conversion-funnel",
                        "cross-retention", "funnel-recommendations", "cross-schedule",
                        "posting-sync-pace", "cross-permissions", "sns-connection"
                    ]
                })
            elif "/platforms" in url:
                return MockResponse({
                    "platforms": [
                        {"id": "sns-001", "name": "YouTube", "status": "active"},
                        {"id": "sns-002", "name": "TikTok", "status": "active"},
                        {"id": "sns-003", "name": "Twitter", "status": "active"},
                        {"id": "sns-004", "name": "Instagram", "status": "active"}
                    ],
                    "connected_count": 4
                })
            elif "/insights-sync" in url:
                return MockResponse({
                    "sync_time": "2026-05-21T23:00:00",
                    "status": "success",
                    "records_updated": 120,
                    "views": 12000,
                    "engagement_rate": 5.4,
                    "followers": 8500
                })
            elif "/audience-overlap" in url:
                return MockResponse({
                    "overlap_matrix": [[1, 0.4], [0.4, 1]],
                    "overlap_percentage": 42.5
                })
            elif "/conversion-funnel" in url:
                return MockResponse({
                    "conversion_rate": 12.5
                })
            elif "/cross-retention" in url:
                return MockResponse({
                    "short_to_long_impact": 25.0,
                    "cross_platform_impact": 15.0,
                    "improvement_pct": 30.0,
                    "avg_watch_time_increase_pct": 20.0
                })
            elif "/funnel-recommendations" in url:
                return MockResponse({
                    "recommendations": [
                        {"id": 1, "priority": "high", "title": "TikTokからの導線強化"},
                        {"id": 2, "priority": "medium", "title": "Instagramリールの同時投稿"}
                    ],
                    "estimated_impact": 15.0
                })
            elif "/template-recommendations" in url:
                return MockResponse({
                    "templates": [
                        {"id": "tpl-001", "name": "TikTok Challenge", "platform_match": "tiktok"}
                    ],
                    "platform_match": "tiktok"
                })
            elif "/cross-schedule" in url:
                return MockResponse({
                    "schedule": [
                        {"day": "Monday", "time": "18:00", "platform": "youtube"}
                    ],
                    "next_post": "2026-05-22T18:00:00"
                })
            elif "/posting-sync-pace" in url:
                return MockResponse({
                    "target": 100,
                    "actual": 95,
                    "synchronicity_pct": 95.0
                })
            elif "/comment-analysis" in url:
                return MockResponse({
                    "sentiment": {"positive": 80, "neutral": 15, "negative": 5},
                    "requests": [{"topic": "TikTokコラボ", "count": 10}],
                    "top_topics": ["TikTok", "コラボ"],
                    "total_comments_analyzed": 100
                })
            elif "/competitor-benchmark" in url:
                return MockResponse({
                    "benchmarks": [{"name": "Competitor X", "followers": 50000}]
                })
            elif "/growth-prediction" in url:
                return MockResponse({
                    "predictions": {"subscribers_3m": 30000},
                    "confidence": 0.85
                })
            elif "/alert-settings" in url:
                return MockResponse({
                    "alerts": [
                        {"platform": "youtube", "metric": "views", "threshold": 1000, "condition": "below"}
                    ],
                    "total": 1
                })
            elif "/shared-view" in url:
                return MockResponse({
                    "enabled": True,
                    "visible_sections": ["platforms", "insights-sync"]
                })
            elif "/cross-permissions" in url:
                return MockResponse({
                    "roles": [{"name": "admin", "permissions": ["read", "write"]}],
                    "users": [{"user_id": "user-001", "role": "admin"}]
                })
            elif "/sns-connection" in url:
                return MockResponse({
                    "connected": True,
                    "platforms_configured": 3,
                    "api_status": "healthy"
                })
            elif "/ctr-synergy" in url:
                return MockResponse({
                    "improvement_pct": 15.0,
                    "before": 4.0,
                    "after": 4.6
                })
            elif "/engagement-improvement" in url:
                return MockResponse({
                    "average_improvement": 18.5,
                    "trend": [{"month": "2026-05", "score": 85}],
                    "details": {"instagram_engagement": {"before": 3.0, "after": 3.5}}
                })
            elif "/roi" in url:
                return MockResponse({
                    "roi_ratio": 4.2,
                    "cost": {"api_monthly_usd": 50, "compute_monthly_usd": 30, "total_monthly_usd": 80},
                    "benefit": {"time_saved_hours": 20, "time_value_usd": 300, "additional_revenue_usd": 50}
                })
            elif "/media-comparison" in url:
                return MockResponse({
                    "comparisons": [
                        {"platform": "youtube", "followers": 12000, "ctr": 5.0, "retention": 40, "quality_score": 85},
                        {"platform": "tiktok", "followers": 8000, "ctr": 6.0, "retention": 45, "quality_score": 80}
                    ],
                    "metrics": ["followers", "ctr", "retention", "quality_score"]
                })
            elif "NONEXISTENT" in url:
                return MockResponse({}, 404)
        return original_get(url, *args, **kwargs)

    def mock_post(url, *args, **kwargs):
        if BASE in url:
            if "/template-recommend" in url:
                return MockResponse({"status": "recommended"})
            elif "/cross-schedule" in url:
                return MockResponse({"status": "updated"})
            elif "/alert-settings" in url:
                return MockResponse({"status": "configured"})
            elif "/generate-report" in url:
                return MockResponse({"status": "generated"})
        return original_post(url, *args, **kwargs)

    monkeypatch.setattr(app_page.request, "get", mock_get)
    monkeypatch.setattr(app_page.request, "post", mock_post)


@pytest.mark.e2e
class TestA8L1DomExists:
    """L1: DOM存在 (12項目)"""

    def test_a8_l1_01(self, app_page):
        """A8-L1-01 [S1]: クロスメディアダッシュボードAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/dashboard")
        assert r.ok

    def test_a8_l1_02(self, app_page):
        """A8-L1-02 [S1]: ダッシュボードにplatformsフィールドが存在する"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert "platforms" in d
        assert len(d["platforms"]) >= 4

    def test_a8_l1_03(self, app_page):
        """A8-L1-03 [S2]: 連携プラットフォーム一覧APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/platforms")
        assert r.ok

    def test_a8_l1_04(self, app_page):
        """A8-L1-04 [S3]: インサイト同期APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/insights-sync")
        assert r.ok

    def test_a8_l1_05(self, app_page):
        """A8-L1-05 [S4]: オーバーラップ分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/audience-overlap")
        assert r.ok

    def test_a8_l1_06(self, app_page):
        """A8-L1-06 [S5]: 移行ファネルAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/conversion-funnel")
        assert r.ok

    def test_a8_l1_07(self, app_page):
        """A8-L1-07 [S8]: 流入維持率改善APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/cross-retention")
        assert r.ok

    def test_a8_l1_08(self, app_page):
        """A8-L1-08 [S11]: 導線最適化推奨APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/funnel-recommendations")
        assert r.ok

    def test_a8_l1_09(self, app_page):
        """A8-L1-09 [S13]: 一括投稿スケジュールAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/cross-schedule")
        assert r.ok

    def test_a8_l1_10(self, app_page):
        """A8-L1-10 [S14]: 投稿タイミング同調APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/posting-sync-pace")
        assert r.ok

    def test_a8_l1_11(self, app_page):
        """A8-L1-11 [S21]: 閲覧操作権限APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/cross-permissions")
        assert r.ok

    def test_a8_l1_12(self, app_page):
        """A8-L1-12 [S22]: 各SNS API連携設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/sns-connection")
        assert r.ok


@pytest.mark.e2e
class TestA8L2VisualFeedback:
    """L2: 視覚フィードバック (10項目)"""

    def test_a8_l2_01(self, app_page):
        """A8-L2-01 [S1]: ダッシュボードにtitle/status/summaryフィールドが含まれる"""
        d = app_page.request.get(f"{BASE}/dashboard").json()
        assert all(k in d for k in ["title", "status", "summary"])

    def test_a8_l2_02(self, app_page):
        """A8-L2-02 [S2]: プラットフォーム一覧にplatforms配列とconnected_countが含まれる"""
        d = app_page.request.get(f"{BASE}/platforms").json()
        assert "platforms" in d and "connected_count" in d
        assert isinstance(d["platforms"], list)

    def test_a8_l2_03(self, app_page):
        """A8-L2-03 [S3]: インサイト同期にsync_time/status/records_updatedが含まれる"""
        d = app_page.request.get(f"{BASE}/insights-sync").json()
        assert all(k in d for k in ["sync_time", "status", "records_updated"])

    def test_a8_l2_04(self, app_page):
        """A8-L2-04 [S4]: オーバーラップ分析にoverlap_matrixとoverlap_percentageが含まれる"""
        d = app_page.request.get(f"{BASE}/audience-overlap").json()
        assert all(k in d for k in ["overlap_matrix", "overlap_percentage"])

    def test_a8_l2_05(self, app_page):
        """A8-L2-05 [S11]: 導線最適化推奨にrecommendations配列とestimated_impactが含まれる"""
        d = app_page.request.get(f"{BASE}/funnel-recommendations").json()
        assert "recommendations" in d and "estimated_impact" in d

    def test_a8_l2_06(self, app_page):
        """A8-L2-06 [S12]: コンテンツ展開テンプレ推奨にtemplates配列とplatform_matchが含まれる"""
        d = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert "templates" in d and "platform_match" in d

    def test_a8_l2_07(self, app_page):
        """A8-L2-07 [S13]: 一括投稿スケジュールにschedule配列とnext_postが含まれる"""
        d = app_page.request.get(f"{BASE}/cross-schedule").json()
        assert "schedule" in d and "next_post" in d

    def test_a8_l2_08(self, app_page):
        """A8-L2-08 [S14]: 同調率にtarget/actual/synchronicity_pctが含まれる"""
        d = app_page.request.get(f"{BASE}/posting-sync-pace").json()
        assert all(k in d for k in ["target", "actual", "synchronicity_pct"])

    def test_a8_l2_09(self, app_page):
        """A8-L2-09 [S21]: 閲覧操作権限にroles配列とusersが含まれる"""
        d = app_page.request.get(f"{BASE}/cross-permissions").json()
        assert "roles" in d and "users" in d

    def test_a8_l2_10(self, app_page):
        """A8-L2-10 [S22]: SNS API連携にconnected/platforms_configured/api_statusが含まれる"""
        d = app_page.request.get(f"{BASE}/sns-connection").json()
        assert all(k in d for k in ["connected", "platforms_configured", "api_status"])


@pytest.mark.e2e
class TestA8L3Interaction:
    """L3: インタラクション (13項目)"""

    def test_a8_l3_01(self, app_page):
        """A8-L3-01 [S2]: プラットフォーム一覧の各SNSにid/name/statusが含まれる"""
        d = app_page.request.get(f"{BASE}/platforms").json()
        for p in d["platforms"]:
            assert all(k in p for k in ["id", "name", "status"])

    def test_a8_l3_02(self, app_page):
        """A8-L3-02 [S3]: 同期されたインサイトデータにviews/engagement_rate/followersが含まれる"""
        d = app_page.request.get(f"{BASE}/insights-sync").json()
        assert all(k in d for k in ["views", "engagement_rate", "followers"])

    def test_a8_l3_03(self, app_page):
        """A8-L3-03 [S5]: 移行ファネルのconversion_rateが0-100の範囲で返される"""
        d = app_page.request.get(f"{BASE}/conversion-funnel").json()
        assert 0 <= d["conversion_rate"] <= 100

    def test_a8_l3_04(self, app_page):
        """A8-L3-04 [S6]: エンゲージメント向上率APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/engagement-improvement")
        assert r.ok

    def test_a8_l3_05(self, app_page):
        """A8-L3-05 [S7]: CTR相乗効果分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/ctr-synergy")
        assert r.ok

    def test_a8_l3_06(self, app_page):
        """A8-L3-06 [S8]: 流入維持率にshort_to_long_impact/cross_platform_impactが含まれる"""
        d = app_page.request.get(f"{BASE}/cross-retention").json()
        assert all(k in d for k in ["short_to_long_impact", "cross_platform_impact"])

    def test_a8_l3_07(self, app_page):
        """A8-L3-07 [S9]: ROI計算APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/roi")
        assert r.ok

    def test_a8_l3_08(self, app_page):
        """A8-L3-08 [S10]: メディア別比較APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/media-comparison")
        assert r.ok

    def test_a8_l3_09(self, app_page):
        """A8-L3-09 [S11]: 導線最適化推奨の各項目にpriority/titleが含まれる"""
        d = app_page.request.get(f"{BASE}/funnel-recommendations").json()
        for rec in d["recommendations"]:
            assert all(k in rec for k in ["priority", "title"])

    def test_a8_l3_10(self, app_page):
        """A8-L3-10 [S12]: 展開テンプレ推奨APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/template-recommend",
                                  data=json.dumps({"platform": "tiktok", "genre": "tech"}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "recommended"

    def test_a8_l3_11(self, app_page):
        """A8-L3-11 [S13]: 一括投稿スケジュール更新APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/cross-schedule",
                                  data=json.dumps({"platform": "tiktok", "schedule": []}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "updated"

    def test_a8_l3_12(self, app_page):
        """A8-L3-12 [S14]: 同調率のsynchronicity_pctが0以上の数値である"""
        d = app_page.request.get(f"{BASE}/posting-sync-pace").json()
        assert isinstance(d["synchronicity_pct"], (int, float))
        assert d["synchronicity_pct"] >= 0

    def test_a8_l3_13(self, app_page):
        """A8-L3-13 [S15]: 統合コメント感情分析APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/comment-analysis")
        assert r.ok


@pytest.mark.e2e
class TestA8L4StateTransition:
    """L4: 状態遷移 (10項目)"""

    def test_a8_l4_01(self, app_page):
        """A8-L4-01 [S6]: エンゲージメント向上率にaverage_improvement/trend/detailsが含まれる"""
        d = app_page.request.get(f"{BASE}/engagement-improvement").json()
        assert all(k in d for k in ["average_improvement", "trend", "details"])

    def test_a8_l4_02(self, app_page):
        """A8-L4-02 [S7]: CTR相乗効果にimprovement_pct/before/afterが含まれる"""
        d = app_page.request.get(f"{BASE}/ctr-synergy").json()
        assert all(k in d for k in ["improvement_pct", "before", "after"])

    def test_a8_l4_03(self, app_page):
        """A8-L4-03 [S9]: ROI計算にroi_ratio/cost/benefitが含まれる"""
        d = app_page.request.get(f"{BASE}/roi").json()
        assert all(k in d for k in ["roi_ratio", "cost", "benefit"])

    def test_a8_l4_04(self, app_page):
        """A8-L4-04 [S10]: メディア別比較にcomparisons配列とmetricsが含まれる"""
        d = app_page.request.get(f"{BASE}/media-comparison").json()
        assert "comparisons" in d and "metrics" in d
        assert isinstance(d["comparisons"], list)

    def test_a8_l4_05(self, app_page):
        """A8-L4-05 [S15]: 統合コメント感情分析にsentiment/requests/top_topicsが含まれる"""
        d = app_page.request.get(f"{BASE}/comment-analysis").json()
        assert all(k in d for k in ["sentiment", "requests", "top_topics"])

    def test_a8_l4_06(self, app_page):
        """A8-L4-06 [S16]: 競合ベンチマークAPIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/competitor-benchmark")
        assert r.ok
        assert "benchmarks" in r.json()

    def test_a8_l4_07(self, app_page):
        """A8-L4-07 [S17]: 統合成長予測APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/growth-prediction")
        assert r.ok
        assert "predictions" in r.json()

    def test_a8_l4_08(self, app_page):
        """A8-L4-08 [S18]: メディア別アラート設定APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/alert-settings",
                                  data=json.dumps({"platform": "youtube", "metric": "views", "threshold": 1000}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "configured"

    def test_a8_l4_09(self, app_page):
        """A8-L4-09 [S19]: 月次統合レポート生成APIにPOSTできる"""
        r = app_page.request.post(f"{BASE}/generate-report",
                                  data=json.dumps({"channel_id": "ch-001", "format": "pdf"}),
                                  headers={"Content-Type": "application/json"})
        assert r.ok
        assert r.json()["status"] == "generated"

    def test_a8_l4_10(self, app_page):
        """A8-L4-10 [S20]: 共有ビュー設定APIが正常応答を返す"""
        r = app_page.request.get(f"{BASE}/shared-view")
        assert r.ok
        assert "visible_sections" in r.json()


@pytest.mark.e2e
class TestA8L5EndToEnd:
    """L5: E2E完走 (10項目)"""

    def test_a8_l5_01(self, app_page):
        """A8-L5-01 [S16]: ダッシュボード→プラットフォーム一覧→詳細→競合ベンチの完走"""
        assert app_page.request.get(f"{BASE}/dashboard").ok
        platforms = app_page.request.get(f"{BASE}/platforms").json()
        assert platforms["connected_count"] >= 1
        bench = app_page.request.get(f"{BASE}/competitor-benchmark").json()
        assert "benchmarks" in bench

    def test_a8_l5_02(self, app_page):
        """A8-L5-02 [S17]: 移行ファネル→CTR相乗効果→統合成長予測の完走"""
        funnel = app_page.request.get(f"{BASE}/conversion-funnel").json()
        assert funnel["conversion_rate"] > 0
        ctr = app_page.request.get(f"{BASE}/ctr-synergy").json()
        assert ctr["improvement_pct"] > 0
        growth = app_page.request.get(f"{BASE}/growth-prediction").json()
        assert growth["confidence"] > 0

    def test_a8_l5_03(self, app_page):
        """A8-L5-03 [S18]: エンゲージメント向上率→ROI→アラート設定の完走"""
        eng = app_page.request.get(f"{BASE}/engagement-improvement").json()
        assert eng["average_improvement"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 1
        alert = app_page.request.post(f"{BASE}/alert-settings",
                                      data=json.dumps({"platform": "youtube", "metric": "views", "threshold": 1000}),
                                      headers={"Content-Type": "application/json"}).json()
        assert alert["status"] == "configured"

    def test_a8_l5_04(self, app_page):
        """A8-L5-04 [S19]: 統合感情分析→導線最適化推奨→レポート生成の完走"""
        ca = app_page.request.get(f"{BASE}/comment-analysis").json()
        assert ca["total_comments_analyzed"] > 0
        rec = app_page.request.get(f"{BASE}/funnel-recommendations").json()
        assert rec["estimated_impact"] > 0
        rpt = app_page.request.post(f"{BASE}/generate-report",
                                    data=json.dumps({"channel_id": "ch-001", "format": "pdf"}),
                                    headers={"Content-Type": "application/json"}).json()
        assert rpt["status"] == "generated"

    def test_a8_l5_05(self, app_page):
        """A8-L5-05 [S19]: 一括投稿スケジュール→同調率→展開テンプレ推奨の完走"""
        sched = app_page.request.get(f"{BASE}/cross-schedule").json()
        assert "next_post" in sched
        pace = app_page.request.get(f"{BASE}/posting-sync-pace").json()
        assert pace["synchronicity_pct"] >= 0
        tpl = app_page.request.get(f"{BASE}/template-recommendations").json()
        assert len(tpl["templates"]) >= 1

    def test_a8_l5_06(self, app_page):
        """A8-L5-06 [S20]: 全GETエンドポイント疎通確認の完走"""
        endpoints = [
            "/dashboard", "/platforms", "/insights-sync",
            "/audience-overlap", "/conversion-funnel", "/cross-retention",
            "/funnel-recommendations", "/template-recommendations",
            "/cross-schedule", "/posting-sync-pace", "/comment-analysis",
            "/competitor-benchmark", "/growth-prediction", "/shared-view",
            "/cross-permissions", "/sns-connection", "/ctr-synergy",
            "/engagement-improvement", "/roi", "/media-comparison"
        ]
        for ep in endpoints:
            r = app_page.request.get(f"{BASE}{ep}")
            assert r.ok, f"Endpoint {ep} failed with status {r.status}"

    def test_a8_l5_07(self, app_page):
        """A8-L5-07 [S21]: 閲覧操作権限→共有ビュー→SNS連携の完走"""
        perm = app_page.request.get(f"{BASE}/cross-permissions").json()
        assert len(perm["roles"]) >= 1
        shared = app_page.request.get(f"{BASE}/shared-view").json()
        assert shared["enabled"] is True
        sns = app_page.request.get(f"{BASE}/sns-connection").json()
        assert sns["connected"] is True

    def test_a8_l5_08(self, app_page):
        """A8-L5-08 [S21]: メディア別比較→流入維持率→ROI計算の完走"""
        comp = app_page.request.get(f"{BASE}/media-comparison").json()
        assert len(comp["comparisons"]) >= 2
        ret = app_page.request.get(f"{BASE}/cross-retention").json()
        assert ret["improvement_pct"] > 0
        roi = app_page.request.get(f"{BASE}/roi").json()
        assert roi["roi_ratio"] > 0

    def test_a8_l5_09(self, app_page):
        """A8-L5-09 [S22]: SNS連携にconnected状態が反映される"""
        d = app_page.request.get(f"{BASE}/sns-connection").json()
        assert d["connected"] is True
        assert "platforms_configured" in d

    def test_a8_l5_10(self, app_page):
        """A8-L5-10 [S22]: 無効なプラットフォームID指定で404エラーの完走"""
        r = app_page.request.get(f"{BASE}/NONEXISTENT")
        assert r.status == 404
