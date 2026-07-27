import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.admin_channel_router import router, _channels

class TestAdminChannelRouterCoverage:
    @pytest.fixture(autouse=True)
    def setup_client(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_dashboard_partial(self):
        # デフォルト状態 (_channelsにpausedが含まれる)
        r = self.client.get("/api/admin/channel/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "partial"
        assert data["summary"]["total_channels"] == 3
        assert data["summary"]["active_channels"] == 2

    def test_dashboard_healthy(self):
        # 全てのチャンネルをactiveにする
        original_channels = [{"status": ch["status"]} for ch in _channels]
        try:
            for ch in _channels:
                ch["status"] = "active"
            r = self.client.get("/api/admin/channel/dashboard")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "healthy"
        finally:
            # 状態を元に戻す
            for i, ch in enumerate(original_channels):
                _channels[i]["status"] = ch["status"]

    def test_get_channels(self):
        r = self.client.get("/api/admin/channel/channels")
        assert r.status_code == 200
        data = r.json()
        assert "channels" in data
        assert data["total"] == 3

    def test_get_channel_detail_success(self):
        r = self.client.get("/api/admin/channel/channels/ch-001")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Antigravity Tech"
        assert data["kpi"]["subscribers"] == 12500

    def test_get_channel_detail_not_found(self):
        r = self.client.get("/api/admin/channel/channels/nonexistent")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_get_effect_summary(self):
        r = self.client.get("/api/admin/channel/effect-summary")
        assert r.status_code == 200
        data = r.json()
        assert "before" in data
        assert "after" in data
        assert data["improvement_pct"]["production_time"] == 68.75

    def test_get_production_efficiency(self):
        r = self.client.get("/api/admin/channel/production-efficiency")
        assert r.status_code == 200
        data = r.json()
        assert data["reduction_pct"] == 68.75

    def test_get_quality_improvement(self):
        r = self.client.get("/api/admin/channel/quality-improvement")
        assert r.status_code == 200
        data = r.json()
        assert data["average_improvement"] == 27.78

    def test_get_ctr_improvement(self):
        r = self.client.get("/api/admin/channel/ctr-improvement")
        assert r.status_code == 200
        data = r.json()
        assert data["improvement_pct"] == 61.90

    def test_get_retention_improvement(self):
        r = self.client.get("/api/admin/channel/retention-improvement")
        assert r.status_code == 200
        data = r.json()
        assert data["improvement_pct"] == 48.57

    def test_get_roi(self):
        r = self.client.get("/api/admin/channel/roi")
        assert r.status_code == 200
        data = r.json()
        assert data["roi_ratio"] == 5.2

    def test_get_channel_comparison(self):
        r = self.client.get("/api/admin/channel/channel-comparison")
        assert r.status_code == 200
        data = r.json()
        assert data["best_performer"] == "ch-001"

    def test_get_optimization_recommendations(self):
        r = self.client.get("/api/admin/channel/optimization-recommendations")
        assert r.status_code == 200
        data = r.json()
        assert data["prioritized_count"] == 3

    def test_get_template_recommendations(self):
        r = self.client.get("/api/admin/channel/template-recommendations")
        assert r.status_code == 200
        data = r.json()
        assert len(data["templates"]) == 3

    def test_post_template_recommend(self):
        r = self.client.post("/api/admin/channel/template-recommend",
                             json={"channel_id": "ch-001", "genre": "creative"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "recommended"
        assert data["genre"] == "creative"

    def test_get_post_schedule(self):
        r = self.client.get("/api/admin/channel/post-schedule")
        assert r.status_code == 200
        data = r.json()
        assert "schedule" in data

    def test_post_post_schedule(self):
        r = self.client.post("/api/admin/channel/post-schedule",
                             json={"channel_id": "ch-001", "schedule": [{"day": "Tuesday", "time": "20:00"}]})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "updated"
        assert data["schedule"][0]["day"] == "Tuesday"

    def test_get_posting_pace(self):
        r = self.client.get("/api/admin/channel/posting-pace")
        assert r.status_code == 200
        data = r.json()
        assert data["achievement_pct"] == 90.0

    def test_get_comment_analysis(self):
        r = self.client.get("/api/admin/channel/comment-analysis")
        assert r.status_code == 200
        data = r.json()
        assert data["sentiment"]["positive"] == 72

    def test_get_competitor_benchmark(self):
        r = self.client.get("/api/admin/channel/competitor-benchmark")
        assert r.status_code == 200
        data = r.json()
        assert data["ranking"]["ctr"] == 1

    def test_get_growth_prediction(self):
        r = self.client.get("/api/admin/channel/growth-prediction")
        assert r.status_code == 200
        data = r.json()
        assert data["confidence"] == 0.78

    def test_get_alert_settings(self):
        r = self.client.get("/api/admin/channel/alert-settings")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

    def test_post_alert_settings(self):
        r = self.client.post("/api/admin/channel/alert-settings",
                             json={"channel_id": "ch-001", "metric": "views", "threshold": 10000.0, "condition": "below"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "configured"
        assert data["metric"] == "views"

    def test_post_generate_report(self):
        r = self.client.post("/api/admin/channel/generate-report",
                             json={"channel_id": "ch-001", "format": "pdf", "period": "weekly"})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "generated"
        assert data["format"] == "pdf"

    def test_get_owner_view(self):
        r = self.client.get("/api/admin/channel/owner-view")
        assert r.status_code == 200
        data = r.json()
        assert data["theme"] == "light"

    def test_get_permissions(self):
        r = self.client.get("/api/admin/channel/permissions")
        assert r.status_code == 200
        data = r.json()
        assert "roles" in data

    def test_get_youtube_connection(self):
        r = self.client.get("/api/admin/channel/youtube-connection")
        assert r.status_code == 200
        data = r.json()
        assert data["connected"] is True
