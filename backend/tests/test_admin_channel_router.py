"""
Unit tests for backend/routers/admin_channel_router.py
Provides 100% coverage by testing all endpoints and error-handling branches.
"""

import os
import sys
import copy
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Ensure the workspace root directory is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Include backend subdirectory in python path as well to allow routers.* imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend"))

# google-genai および MCP に起因する Pydantic の ValueError (Python 3.13 互換性バグ) を回避するため、
# インポート前に sys.modules に google.genai 関連のモックを登録し、本物のインポートをバイパスする
from unittest.mock import MagicMock
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.types'] = MagicMock()

# Global admin_module definition for lazy loading
admin_module = None

def get_admin_module():
    global admin_module
    if admin_module is None:
        import routers.admin_channel_router
        import sys
        admin_module = sys.modules["routers.admin_channel_router"]
    return admin_module

@pytest.fixture
def client():
    mod = get_admin_module()
    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)

@pytest.fixture(autouse=True)
def reset_state():
    mod = get_admin_module()
    orig_channels = copy.deepcopy(mod._channels)
    orig_permissions = copy.deepcopy(mod._permissions)
    yield
    mod._channels = orig_channels
    mod._permissions = orig_permissions

# S1: Dashboard
def test_get_dashboard(client):
    response = client.get("/api/admin/channel/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "チャンネル主ダッシュボード管理"
    assert "summary" in data
    assert "sections" in data

def test_get_dashboard_partial_status(client):
    # Change status of one channel to make status "partial"
    mod = get_admin_module()
    mod._channels[0]["status"] = "paused"
    response = client.get("/api/admin/channel/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"

# S2: Channels
def test_get_channels(client):
    response = client.get("/api/admin/channel/channels")
    assert response.status_code == 200
    data = response.json()
    assert "channels" in data
    assert len(data["channels"]) == 3

# S3: Channel Detail
def test_get_channel_detail_success(client):
    response = client.get("/api/admin/channel/channels/ch-001")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Antigravity Tech"
    assert "kpi" in data
    assert "settings" in data

def test_get_channel_detail_not_found(client):
    response = client.get("/api/admin/channel/channels/non_existent_channel_id")
    assert response.status_code == 404
    assert "Channel non_existent_channel_id not found" in response.json()["detail"]

# S4: Effect Summary
def test_get_effect_summary(client):
    response = client.get("/api/admin/channel/effect-summary")
    assert response.status_code == 200
    data = response.json()
    assert "before" in data
    assert "after" in data
    assert "improvement_pct" in data

# S5: Production Efficiency
def test_get_production_efficiency(client):
    response = client.get("/api/admin/channel/production-efficiency")
    assert response.status_code == 200
    data = response.json()
    assert "reduction_pct" in data
    assert "breakdown" in data

# S6: Quality Improvement
def test_get_quality_improvement(client):
    response = client.get("/api/admin/channel/quality-improvement")
    assert response.status_code == 200
    data = response.json()
    assert "average_improvement" in data
    assert "trend" in data

# S7: CTR Improvement
def test_get_ctr_improvement(client):
    response = client.get("/api/admin/channel/ctr-improvement")
    assert response.status_code == 200
    data = response.json()
    assert "improvement_pct" in data
    assert "factors" in data

# S8: Retention Improvement
def test_get_retention_improvement(client):
    response = client.get("/api/admin/channel/retention-improvement")
    assert response.status_code == 200
    data = response.json()
    assert "improvement_pct" in data
    assert "smartcut_impact" in data

# S9: ROI
def test_get_roi(client):
    response = client.get("/api/admin/channel/roi")
    assert response.status_code == 200
    data = response.json()
    assert "roi_ratio" in data
    assert "cost" in data

# S10: Channel Comparison
def test_get_channel_comparison(client):
    response = client.get("/api/admin/channel/channel-comparison")
    assert response.status_code == 200
    data = response.json()
    assert "comparisons" in data
    assert data["best_performer"] == "ch-001"

# S11: Optimization Recommendations
def test_get_optimization_recommendations(client):
    response = client.get("/api/admin/channel/optimization-recommendations")
    assert response.status_code == 200
    data = response.json()
    assert "recommendations" in data
    assert data["prioritized_count"] == 3

# S12: Template Recommendations
def test_get_template_recommendations(client):
    response = client.get("/api/admin/channel/template-recommendations")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert data["genre_match"] == "tech"

def test_recommend_template_success(client):
    payload = {"channel_id": "ch-001", "genre": "tech"}
    response = client.post("/api/admin/channel/template-recommend", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recommended"
    assert data["channel_id"] == "ch-001"
    assert data["genre"] == "tech"

# S13: Post Schedule
def test_get_post_schedule(client):
    response = client.get("/api/admin/channel/post-schedule")
    assert response.status_code == 200
    data = response.json()
    assert "schedule" in data
    assert "next_post" in data

def test_update_post_schedule_success(client):
    payload = {
        "channel_id": "ch-001",
        "schedule": [{"day": "Friday", "time": "20:00", "type": "vlog"}]
    }
    response = client.post("/api/admin/channel/post-schedule", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["channel_id"] == "ch-001"
    assert data["schedule"][0]["day"] == "Friday"

# S14: Posting Pace
def test_get_posting_pace(client):
    response = client.get("/api/admin/channel/posting-pace")
    assert response.status_code == 200
    data = response.json()
    assert "target" in data
    assert "achievement_pct" in data

# S15: Comment Analysis
def test_get_comment_analysis(client):
    response = client.get("/api/admin/channel/comment-analysis")
    assert response.status_code == 200
    data = response.json()
    assert "sentiment" in data
    assert "requests" in data

# S16: Competitor Benchmark
def test_get_competitor_benchmark(client):
    response = client.get("/api/admin/channel/competitor-benchmark")
    assert response.status_code == 200
    data = response.json()
    assert "benchmarks" in data
    assert data["channel_id"] == "ch-001"

# S17: Growth Prediction
def test_get_growth_prediction(client):
    response = client.get("/api/admin/channel/growth-prediction")
    assert response.status_code == 200
    data = response.json()
    assert "predictions" in data
    assert data["channel_id"] == "ch-001"

# S18: Alert Settings
def test_get_alert_settings(client):
    response = client.get("/api/admin/channel/alert-settings")
    assert response.status_code == 200
    data = response.json()
    assert "alerts" in data
    assert data["total"] == 2

def test_update_alert_settings_success(client):
    payload = {
        "channel_id": "ch-001",
        "metric": "ctr",
        "threshold": 4.5,
        "condition": "below"
    }
    response = client.post("/api/admin/channel/alert-settings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "configured"
    assert data["channel_id"] == "ch-001"
    assert data["threshold"] == 4.5

# S19: Generate Report
def test_generate_report_success(client):
    payload = {
        "channel_id": "ch-001",
        "format": "pdf",
        "period": "monthly"
    }
    response = client.post("/api/admin/channel/generate-report", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "generated"
    assert data["channel_id"] == "ch-001"
    assert "download_url" in data

# S20: Owner View
def test_get_owner_view(client):
    response = client.get("/api/admin/channel/owner-view")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert "visible_sections" in data

# S21: Permissions
def test_get_permissions(client):
    response = client.get("/api/admin/channel/permissions")
    assert response.status_code == 200
    data = response.json()
    assert "roles" in data
    assert "users" in data

# S22: YouTube Connection
def test_get_youtube_connection(client):
    response = client.get("/api/admin/channel/youtube-connection")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert "scopes" in data

# Pydantic Validation tests
def test_pydantic_validation_schedule_update():
    mod = get_admin_module()
    with pytest.raises(ValidationError):
        mod.ScheduleUpdateRequest(channel_id="ch-001") # schedule missing

    # Case: day is missing
    with pytest.raises(ValidationError):
        mod.ScheduleUpdateRequest(
            channel_id="ch-001",
            schedule=[{"time": "18:00", "type": "tutorial"}]
        )

    # Case: time is missing
    with pytest.raises(ValidationError):
        mod.ScheduleUpdateRequest(
            channel_id="ch-001",
            schedule=[{"day": "Monday", "type": "tutorial"}]
        )

    # Case: normal data
    req = mod.ScheduleUpdateRequest(
        channel_id="ch-001",
        schedule=[{"day": "Monday", "time": "18:00", "type": "tutorial"}]
    )
    assert len(req.schedule) == 1
    assert req.schedule[0].day == "Monday"
    assert req.schedule[0].time == "18:00"
    assert req.schedule[0].type == "tutorial"


def test_pydantic_validation_template_recommend():
    mod = get_admin_module()
    # check default values
    req = mod.TemplateRecommendRequest(channel_id="ch-001")
    assert req.genre == "tech"

def test_pydantic_validation_alert_setting():
    mod = get_admin_module()
    req = mod.AlertSettingRequest(channel_id="ch-001")
    assert req.metric == "subscribers"
    assert req.threshold == 0.0
    assert req.condition == "below"

def test_pydantic_validation_report_generate():
    mod = get_admin_module()
    req = mod.ReportGenerateRequest(channel_id="ch-001")
    assert req.format == "pdf"
    assert req.period == "monthly"
