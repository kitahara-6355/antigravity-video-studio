import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi import FastAPI

# テスト用の最小限の FastAPI アプリを立ち上げるか、本物のルーターをインポート
from routers.admin_quota_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def mock_usage_tracker():
    tracker = MagicMock()
    tracker.get_today_usage.return_value = {
        "date": "2026-05-31",
        "used": 100,
        "limit": 500,
        "remaining": 400,
        "usage_pct": 20.0,
        "escalation_level": "normal"
    }
    tracker.thresholds = {"info": 0.60, "warning": 0.80, "critical": 0.95}
    tracker.should_block.return_value = False
    tracker.override_active = False
    return tracker

def test_get_dashboard(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        response = client.get("/api/admin/quota/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "API使用量監視"
        assert data["status"] == "NORMAL"
        assert data["usage_summary"]["usage_percent"] == 20.0

def test_get_status(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        response = client.get("/api/admin/quota/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "NORMAL"
        assert data["usage_percent"] == 20.0
        assert data["thresholds"] == {"info": 60.0, "warning": 80.0, "critical": 95.0}

def test_update_thresholds_success(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        # 正常な閾値の更新
        response = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 50.0,
            "warning_percent": 70.0,
            "critical_percent": 90.0
        })
        assert response.status_code == 200
        mock_usage_tracker.update_thresholds.assert_called_once_with(
            info=0.5, warning=0.7, critical=0.9
        )

def test_update_thresholds_invalid_values(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        # ガードレール: info >= warning
        response = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 75.0,
            "warning_percent": 70.0,
            "critical_percent": 90.0
        })
        assert response.status_code == 400
        assert "Thresholds must satisfy" in response.json()["detail"]

        # ガードレール: 範囲外
        response = client.post("/api/admin/quota/thresholds", json={
            "info_percent": -10.0,
            "warning_percent": 70.0,
            "critical_percent": 90.0
        })
        assert response.status_code == 400

def test_override_success(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        # force_use のテスト
        response = client.post("/api/admin/quota/override", json={"action": "force_use"})
        assert response.status_code == 200
        assert response.json()["status"] == "overridden"
        mock_usage_tracker.set_override.assert_called_with(True)

        # release のテスト
        response = client.post("/api/admin/quota/override", json={"action": "release"})
        assert response.status_code == 200
        assert response.json()["status"] == "released"
        mock_usage_tracker.set_override.assert_called_with(False)

def test_override_invalid_action(mock_usage_tracker):
    with patch("routers.admin_quota_router._get_tracker", return_value=mock_usage_tracker):
        # 入力ガードレール
        response = client.post("/api/admin/quota/override", json={"action": "invalid_action_value"})
        assert response.status_code == 400
        assert "Invalid action" in response.json()["detail"]
