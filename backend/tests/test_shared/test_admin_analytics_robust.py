import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from datetime import datetime

class TestAdminAnalyticsRouterRobust:
    """routers/admin_analytics_router.py に対する強固で詳細なユニットテスト"""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from routers.admin_analytics_router import router
        import sys
        mod = sys.modules['routers.admin_analytics_router']

        # インメモリ状態の初期化
        mod._kpi_settings = {"target_ctr": 5.0, "target_retention": 50.0}
        mod._api_connection = {
            "connected": True,
            "update_interval_minutes": 60,
            "last_sync": datetime.now().isoformat(),
            "enabled": True,
        }
        mod._applied_suggestions = []
        mod._improvement_suggestions = [
            {"id": 1, "category": "thumbnail", "impact": "high", "description": "サムネイルにテキストオーバーレイ追加でCTR+1.2%見込み", "applied": False},
            {"id": 2, "category": "smartcut", "impact": "medium", "description": "SmartCut設定をaggressiveに変更で維持率+5%見込み", "applied": False},
            {"id": 3, "category": "chapter", "impact": "medium", "description": "チャプター自動生成の有効化で維持率+3%見込み", "applied": False},
            {"id": 4, "category": "title", "impact": "low", "description": "タイトルに数字/疑問形を含めてCTR+0.5%見込み", "applied": False},
        ]
        mod._video_data = [
            {"id": 1, "title": "AI動画編集入門", "ctr": 4.8, "retention": 52.3, "views": 12500, "published": "2026-04-01"},
            {"id": 2, "title": "SmartCut活用術", "ctr": 5.2, "retention": 48.7, "views": 8900, "published": "2026-04-08"},
            {"id": 3, "title": "テンプレート比較", "ctr": 3.9, "retention": 44.1, "views": 6300, "published": "2026-04-15"},
            {"id": 4, "title": "品質ゲート解説", "ctr": 6.1, "retention": 55.8, "views": 15200, "published": "2026-04-22"},
            {"id": 5, "title": "YouTube最適化ガイド", "ctr": 4.5, "retention": 47.2, "views": 10100, "published": "2026-04-29"},
        ]

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_dashboard_details(self):
        """dashboardエンドポイントのレスポンス構造と値の検証"""
        r = self.client.get("/api/admin/analytics/dashboard")
        assert r.status_code == 200
        data = r.json()
        
        assert data["title"] == "YouTube Analytics連携"
        assert data["status"] == "connected"
        assert data["api_connected"] is True
        
        kpi = data["kpi_summary"]
        assert kpi["avg_ctr"] == 4.9
        assert kpi["avg_retention"] == 49.6
        assert kpi["total_videos"] == 5
        assert kpi["total_views"] == 53000
        
        assert "ctr_trend" in data["sections"]
        assert "growth_forecast" in data["sections"]
        assert "timestamp" in data

    def test_dashboard_disconnected(self):
        """API接続が切れている場合のdashboardレスポンス検証"""
        import sys
        mod = sys.modules['routers.admin_analytics_router']
        mod._api_connection["connected"] = False

        r = self.client.get("/api/admin/analytics/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "disconnected"
        assert data["api_connected"] is False

    def test_ctr_trend_details(self):
        """ctr-trendエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/ctr-trend")
        assert r.status_code == 200
        data = r.json()
        
        assert data["period_days"] == 30
        history = data["history"]
        assert len(history) == 30
        
        for item in history:
            assert "date" in item
            assert isinstance(item["ctr"], float)
            assert 0.0 <= item["ctr"] <= 8.0

    def test_retention_trend_details(self):
        """retention-trendエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/retention-trend")
        assert r.status_code == 200
        data = r.json()
        
        assert data["period_days"] == 30
        history = data["history"]
        assert len(history) == 30
        
        for item in history:
            assert "date" in item
            assert isinstance(item["retention"], float)
            assert 0.0 <= item["retention"] <= 65.0

    def test_video_performance_details(self):
        """video-performanceエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/video-performance")
        assert r.status_code == 200
        data = r.json()
        
        assert data["total"] == 5
        videos = data["videos"]
        assert len(videos) == 5
        
        v1 = videos[0]
        assert v1["id"] == 1
        assert v1["title"] == "AI動画編集入門"
        assert v1["ctr"] == 4.8
        assert v1["retention"] == 52.3
        assert v1["views"] == 12500
        assert "published" in v1

    def test_benchmark_details(self):
        """benchmarkエンドポイントの計算とステータスの検証"""
        r = self.client.get("/api/admin/analytics/benchmark")
        assert r.status_code == 200
        data = r.json()
        
        assert data["industry_avg"]["ctr"] == 3.5
        assert data["industry_avg"]["retention"] == 40.0
        
        assert data["channel_avg"]["ctr"] == 4.9
        assert data["channel_avg"]["retention"] == 49.6
        
        comp = data["comparison"]
        assert comp["ctr_diff"] == round(4.9 - 3.5, 1)
        assert comp["retention_diff"] == round(49.6 - 40.0, 1)
        assert comp["ctr_status"] == "above"
        assert comp["retention_status"] == "above"

    def test_benchmark_below_status(self):
        """チャンネル平均が業界平均を下回る場合のステータス検証"""
        import sys
        mod = sys.modules['routers.admin_analytics_router']
        mod._video_data = [
            {"id": 1, "title": "Bad Video", "ctr": 2.0, "retention": 30.0, "views": 100, "published": "2026-04-01"}
        ]
        
        r = self.client.get("/api/admin/analytics/benchmark")
        assert r.status_code == 200
        data = r.json()
        comp = data["comparison"]
        assert comp["ctr_status"] == "below"
        assert comp["retention_status"] == "below"

    def test_template_effect_details(self):
        """template-effectエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/template-effect")
        assert r.status_code == 200
        data = r.json()
        
        assert data["total"] == 4
        templates = data["templates"]
        assert len(templates) == 4
        assert templates[0]["name"] == "教育・解説系"
        assert templates[0]["avg_ctr"] == 5.1
        assert templates[0]["avg_retention"] == 51.2
        assert templates[0]["video_count"] == 12

    def test_smartcut_effect_details(self):
        """smartcut-effectエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/smartcut-effect")
        assert r.status_code == 200
        data = r.json()
        
        assert data["total"] == 3
        settings = data["settings"]
        assert len(settings) == 3
        assert settings[0]["setting"] == "aggressive"
        assert settings[0]["avg_retention"] == 55.3
        assert "video_count" in settings[0]

    def test_ai_suggestion_effect_details(self):
        """ai-suggestion-effectエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/ai-suggestion-effect")
        assert r.status_code == 200
        data = r.json()
        
        assert data["adopted"]["count"] == 15
        assert data["rejected"]["count"] == 8
        assert data["impact_diff"]["ctr_diff"] == 1.5
        assert data["impact_diff"]["retention_diff"] == 10.8

    def test_chapter_effect_details(self):
        """chapter-effectエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/chapter-effect")
        assert r.status_code == 200
        data = r.json()
        
        assert data["with_chapters"]["avg_retention"] == 53.2
        assert data["without_chapters"]["avg_retention"] == 42.1
        assert data["improvement"]["retention_diff"] == 11.1

    def test_thumbnail_effect_details(self):
        """thumbnail-effectエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/thumbnail-effect")
        assert r.status_code == 200
        data = r.json()
        
        assert len(data["thumbnails"]) == 4
        assert data["correlation_score"] == 0.72
        assert data["best_performing"] == "face_close_up"

    def test_improvement_suggestions_details(self):
        """improvement-suggestionsエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/improvement-suggestions")
        assert r.status_code == 200
        data = r.json()
        
        assert data["total"] == 4
        assert len(data["suggestions"]) == 4
        assert data["suggestions"][0]["id"] == 1
        assert data["suggestions"][0]["applied"] is False

    def test_apply_suggestion_success_robust(self):
        """提案適用成功ケースのロバスト検証"""
        r = self.client.get("/api/admin/analytics/improvement-suggestions")
        assert r.json()["suggestions"][0]["applied"] is False

        r = self.client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "applied"
        assert data["suggestion_id"] == 1
        assert "applied_at" in data

        r = self.client.get("/api/admin/analytics/improvement-suggestions")
        assert r.json()["suggestions"][0]["applied"] is True

    def test_apply_suggestion_not_found_robust(self):
        """存在しない提案IDの適用失敗テスト"""
        r = self.client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": 9999})
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_kpi_settings_workflow(self):
        """KPI設定の取得・更新・バリデーションワークフロー"""
        r = self.client.get("/api/admin/analytics/kpi-settings")
        assert r.status_code == 200
        assert r.json()["target_ctr"] == 5.0
        assert r.json()["target_retention"] == 50.0

        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 6.5, "target_retention": 55.0})
        assert r.status_code == 200
        assert r.json()["status"] == "updated"
        assert r.json()["target_ctr"] == 6.5
        assert r.json()["target_retention"] == 55.0

        r = self.client.get("/api/admin/analytics/kpi-settings")
        assert r.json()["target_ctr"] == 6.5

        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": -0.1, "target_retention": 50.0})
        assert r.status_code == 400
        assert "Invalid target_ctr" in r.json()["detail"]

        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 5.0, "target_retention": -10.0})
        assert r.status_code == 400
        assert "Invalid target_retention" in r.json()["detail"]

    def test_kpi_achievement_calculation(self):
        """KPI達成率計算と100%キャップの検証"""
        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 4.0, "target_retention": 40.0})
        assert r.status_code == 200

        r = self.client.get("/api/admin/analytics/kpi-achievement")
        assert r.status_code == 200
        data = r.json()
        assert data["achievement_rate"]["ctr"] == 100.0
        assert data["achievement_rate"]["retention"] == 100.0
        assert data["achievement_rate"]["overall"] == 100.0

        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 10.0, "target_retention": 80.0})
        assert r.status_code == 200

        r = self.client.get("/api/admin/analytics/kpi-achievement")
        data = r.json()
        assert data["achievement_rate"]["ctr"] == 49.0
        assert data["achievement_rate"]["retention"] == 62.0
        assert data["achievement_rate"]["overall"] == 55.5

    def test_kpi_achievement_zero_division_guard(self):
        """KPI設定でゼロに近い値が指定された場合のゼロ除算ガード検証"""
        r = self.client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 0.0, "target_retention": 0.0})
        assert r.status_code == 200

        r = self.client.get("/api/admin/analytics/kpi-achievement")
        assert r.status_code == 200
        data = r.json()
        assert data["achievement_rate"]["ctr"] == 100.0
        assert data["achievement_rate"]["retention"] == 100.0

    def test_trend_analysis_details(self):
        """trend-analysisエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/trend-analysis")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 4
        assert len(data["trends"]) == 4
        assert data["trends"][0]["topic"] == "AI動画編集"
        assert "direction" in data["trends"][0]
        assert "analysis_date" in data

    def test_competitor_analysis_details(self):
        """competitor-analysisエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/competitor-analysis")
        assert r.status_code == 200
        data = r.json()
        assert data["our_rank"] == 2
        assert data["total_compared"] == 3
        assert len(data["competitors"]) == 3

    def test_generate_report_workflow(self):
        """generate-reportのエラーハンドリングと正常系検証"""
        r = self.client.post("/api/admin/analytics/generate-report", json={"period": "weekly"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "generated"
        assert data["period"] == "weekly"
        assert "report_weekly.pdf" in data["download_url"]

        r = self.client.post("/api/admin/analytics/generate-report", json={"period": "monthly"})
        assert r.status_code == 200
        assert r.json()["period"] == "monthly"

        r = self.client.post("/api/admin/analytics/generate-report", json={"period": "invalid_period"})
        assert r.status_code == 400
        assert "Invalid period" in r.json()["detail"]

    def test_api_connection_workflow(self):
        """api-connection設定の取得と更新"""
        r = self.client.get("/api/admin/analytics/api-connection")
        assert r.status_code == 200
        assert r.json()["update_interval_minutes"] == 60
        assert r.json()["enabled"] is True

        r = self.client.post("/api/admin/analytics/api-connection", json={"update_interval_minutes": 15, "enabled": False})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "updated"
        assert data["update_interval_minutes"] == 15
        assert data["enabled"] is False
        assert "last_sync" in data

    def test_cache_fallback_details(self):
        """api_connectionと連動したcache-fallback状態の検証"""
        r = self.client.get("/api/admin/analytics/cache-fallback")
        assert r.status_code == 200
        assert r.json()["fallback_active"] is False
        assert r.json()["data_freshness"] == "fresh"

        import sys
        mod = sys.modules['routers.admin_analytics_router']
        mod._api_connection["connected"] = False

        r = self.client.get("/api/admin/analytics/cache-fallback")
        assert r.status_code == 200
        assert r.json()["fallback_active"] is True
        assert r.json()["data_freshness"] == "cached"

    def test_owner_dashboard_details(self):
        """owner-dashboardエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/owner-dashboard")
        assert r.status_code == 200
        data = r.json()
        
        sum_data = data["summary"]
        assert sum_data["total_videos"] == 5
        assert sum_data["total_views"] == 53000
        assert sum_data["avg_ctr"] == 4.9
        assert sum_data["avg_retention"] == 49.6

        highlights = data["highlights"]
        assert len(highlights) == 3
        assert "CTR平均 4.9%" in highlights[0]
        assert "維持率平均 49.6%" in highlights[1]
        assert "総再生数 53,000" in highlights[2]

    def test_period_comparison_details(self):
        """任意期間の比較分析のパラメータ指定とレスポンス検証"""
        r = self.client.get("/api/admin/analytics/period-comparison")
        assert r.status_code == 200
        data = r.json()
        assert data["period1"]["label"] == "2026-03"
        assert data["period2"]["label"] == "2026-04"
        assert data["diff"]["ctr_change"] == 0.8

        r = self.client.get("/api/admin/analytics/period-comparison?period1=2026-05&period2=2026-06")
        assert r.status_code == 200
        data = r.json()
        assert data["period1"]["label"] == "2026-05"
        assert data["period2"]["label"] == "2026-06"

    def test_growth_forecast_details(self):
        """growth-forecastエンドポイントの検証"""
        r = self.client.get("/api/admin/analytics/growth-forecast")
        assert r.status_code == 200
        data = r.json()
        
        assert data["forecast_subscribers"]["current"] == 15000
        assert data["forecast_views"]["current_monthly"] == 53000
        assert data["growth_rate"]["subscribers_monthly_pct"] == 14.7
        assert data["confidence"] == 0.82
        assert "generated_at" in data
