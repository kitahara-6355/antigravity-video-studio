import sys
import pydantic.root_model
sys.modules['pydantic.root_model'] = pydantic.root_model

"""
Admin Quota Router Coverage Boost Tests

admin_quota_router.py の未カバー行を網羅し、カバレッジ100%を達成するためのテスト。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.admin_quota_router import router
from usage_tracker.api_usage_tracker import usage_tracker

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

class TestAdminQuotaCoverageBoost:
    """admin_quota_router.py の未カバー行（例外、ステータス遷移、キーローテーション、ブロック処理など）を網羅するテストクラス"""

    def test_thresholds_invalid_values(self, client):
        # 1. 範囲外の閾値設定 (val < 0)
        r = client.post("/api/admin/quota/thresholds", json={
            "info_percent": -5.0,
            "warning_percent": 80.0,
            "critical_percent": 95.0
        })
        assert r.status_code == 400
        assert "Invalid threshold info" in r.json()["detail"]

        # 2. 範囲外の閾値設定 (val > 100)
        r = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 60.0,
            "warning_percent": 120.0,
            "critical_percent": 95.0
        })
        assert r.status_code == 400
        assert "Invalid threshold warning" in r.json()["detail"]

        # 3. 順序が正しくない閾値設定 (info >= warning)
        r = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 75.0,
            "warning_percent": 70.0,
            "critical_percent": 95.0
        })
        assert r.status_code == 400
        assert "Thresholds must satisfy info < warning < critical" in r.json()["detail"]

        # 4. 順序が正しくない閾値設定 (warning >= critical)
        r = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 60.0,
            "warning_percent": 95.0,
            "critical_percent": 90.0
        })
        assert r.status_code == 400
        assert "Thresholds must satisfy info < warning < critical" in r.json()["detail"]

    def test_auto_block_trigger_and_release(self, client):
        # 1. ブロック強制トリガー
        r = client.post("/api/admin/quota/auto-block/trigger")
        assert r.status_code == 200
        assert r.json()["status"] == "triggered"
        assert r.json()["blocked"] is True

        # 2. ステータス確認
        r = client.get("/api/admin/quota/auto-block")
        assert r.status_code == 200
        data = r.json()
        assert data["blocked"] is True
        assert data["reason"] == "API使用量がサスペンド閾値を超えました"
        assert data["triggered_at"] is not None

        # 3. ブロック解除
        r = client.post("/api/admin/quota/auto-block/release")
        assert r.status_code == 200
        assert r.json()["status"] == "released"
        assert r.json()["blocked"] is False

        # 4. ステータス確認（解除後）
        r = client.get("/api/admin/quota/auto-block")
        assert r.status_code == 200
        assert r.json()["blocked"] is False
        assert r.json()["reason"] is None
        assert r.json()["triggered_at"] is None

    def test_alert_history_filtering(self, client):
        # 1. WARNINGレベルでフィルタリング
        r = client.get("/api/admin/quota/alerts?level=warning")
        assert r.status_code == 200
        data = r.json()
        for alert in data["alerts"]:
            assert alert["level"] == "WARNING"

        # 2. CRITICALレベルでフィルタリング
        r = client.get("/api/admin/quota/alerts?level=critical")
        assert r.status_code == 200
        data = r.json()
        for alert in data["alerts"]:
            assert alert["level"] == "CRITICAL"

        # 3. INFOレベルでフィルタリング
        r = client.get("/api/admin/quota/alerts?level=info")
        assert r.status_code == 200
        data = r.json()
        for alert in data["alerts"]:
            assert alert["level"] == "INFO"

    def test_export_report_invalid_format(self, client):
        # 1. 無効なフォーマット
        r = client.post("/api/admin/quota/export", json={"format": "txt"})
        assert r.status_code == 400
        assert "Invalid format: txt" in r.json()["detail"]

        # 2. 有効なフォーマット（PDF）
        r = client.post("/api/admin/quota/export", json={"format": "pdf"})
        assert r.status_code == 200
        assert r.json()["format"] == "pdf"

    def test_key_rotation_crud(self, client):
        # 1. 短すぎるAPIキー (len < 10)
        r = client.post("/api/admin/quota/key-rotation", json={
            "key_name": "test_short_key",
            "api_key": "short"
        })
        assert r.status_code == 400
        assert "API key too short" in r.json()["detail"]

        # 2. 正常なAPIキー追加
        key_name = "test_rotation_key"
        api_key = "abcdefghijklmn_secret_123"
        r = client.post("/api/admin/quota/key-rotation", json={
            "key_name": key_name,
            "api_key": api_key
        })
        assert r.status_code == 200
        assert r.json()["status"] == "added"
        assert r.json()["key_name"] == key_name
        assert r.json()["prefix"] == "abcdefgh..."

        # 3. キー一覧取得
        r = client.get("/api/admin/quota/key-rotation")
        assert r.status_code == 200
        assert any(k["key_name"] == key_name for k in r.json()["keys"])

        # 4. キー削除
        r = client.delete(f"/api/admin/quota/key-rotation/{key_name}")
        assert r.status_code == 200
        assert r.json()["status"] == "removed"
        assert r.json()["key_name"] == key_name

        # 5. 存在しないキーの削除（例外）
        r = client.delete(f"/api/admin/quota/key-rotation/{key_name}")
        assert r.status_code == 404
        assert f"Key '{key_name}' not found" in r.json()["detail"]

    def test_update_budget_invalid_value(self, client):
        # 1. 負の予算上限
        r = client.post("/api/admin/quota/budget", json={"monthly_limit_jpy": -100.0})
        assert r.status_code == 400
        assert "Budget limit must be non-negative" in r.json()["detail"]

    def test_compute_status_by_varying_usage(self, client):
        original_data = usage_tracker._data.copy()
        original_thresholds = usage_tracker.thresholds.copy()
        today = usage_tracker._today()

        try:
            # 閾値を標準値に固定
            usage_tracker.thresholds["info"] = 0.60
            usage_tracker.thresholds["warning"] = 0.80
            usage_tracker.thresholds["critical"] = 0.95
            limit = usage_tracker._data.get("limit", 500)

            # 1. NORMAL (使用率 50%)
            usage_tracker._data["daily"][today] = {"total": int(limit * 0.5), "sources": {}}
            r = client.get("/api/admin/quota/status")
            assert r.status_code == 200
            assert r.json()["status"] == "NORMAL"
            assert r.json()["color"] == "#22c55e"
            assert "正常範囲内" in r.json()["description"]

            # 2. INFO (使用率 70%)
            usage_tracker._data["daily"][today] = {"total": int(limit * 0.7), "sources": {}}
            r = client.get("/api/admin/quota/status")
            assert r.status_code == 200
            assert r.json()["status"] == "INFO"
            assert r.json()["color"] == "#3b82f6"
            assert "注意レベル" in r.json()["description"]

            # 3. WARNING (使用率 85%)
            usage_tracker._data["daily"][today] = {"total": int(limit * 0.85), "sources": {}}
            r = client.get("/api/admin/quota/status")
            assert r.status_code == 200
            assert r.json()["status"] == "WARNING"
            assert r.json()["color"] == "#f59e0b"
            assert "警告レベル" in r.json()["description"]

            # 4. CRITICAL (使用率 98%)
            usage_tracker._data["daily"][today] = {"total": int(limit * 0.98), "sources": {}}
            r = client.get("/api/admin/quota/status")
            assert r.status_code == 200
            assert r.json()["status"] == "BLOCKED"
            assert r.json()["color"] == "#ef4444"
            assert "危険レベル" in r.json()["description"]

            # 5. 不正なステータス時のフォールバック色確認（直接関数呼び出しでカバレッジ確保）
            from routers.admin_quota_router import _status_color, _status_description
            assert _status_color("UNKNOWN") == "#6b7280"
            assert _status_description("UNKNOWN") == "不明"

        finally:
            # 元の状態に復元
            usage_tracker._data = original_data
            usage_tracker.thresholds = original_thresholds

    def test_get_endpoints_coverage(self, client):
        # GET /dashboard
        r = client.get("/api/admin/quota/dashboard")
        assert r.status_code == 200
        assert r.json()["title"] == "API使用量監視"

        # GET /usage-gauge
        r = client.get("/api/admin/quota/usage-gauge")
        assert r.status_code == 200
        assert "daily" in r.json()

        # GET /remaining
        r = client.get("/api/admin/quota/remaining")
        assert r.status_code == 200
        assert "remaining" in r.json()

        # GET /usage-history
        r = client.get("/api/admin/quota/usage-history")
        assert r.status_code == 200
        assert "history" in r.json()

        # GET /model-breakdown
        r = client.get("/api/admin/quota/model-breakdown")
        assert r.status_code == 200
        assert "premium" in r.json()

        # GET /worker-breakdown
        r = client.get("/api/admin/quota/worker-breakdown")
        assert r.status_code == 200
        assert "workers" in r.json()

        # GET /cost-estimate
        r = client.get("/api/admin/quota/cost-estimate")
        assert r.status_code == 200
        assert "estimated" in r.json()

        # GET /thresholds & POST /thresholds (valid)
        r = client.get("/api/admin/quota/thresholds")
        assert r.status_code == 200
        assert r.json()["info"] == 60.0

        r = client.post("/api/admin/quota/thresholds", json={
            "info_percent": 65.0,
            "warning_percent": 85.0,
            "critical_percent": 98.0
        })
        assert r.status_code == 200
        assert r.json()["info"] == 65.0

        # GET /saving-mode & POST /saving-mode
        r = client.get("/api/admin/quota/saving-mode")
        assert r.status_code == 200
        assert r.json()["enabled"] is False

        r = client.post("/api/admin/quota/saving-mode", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

        # GET /forecast
        r = client.get("/api/admin/quota/forecast")
        assert r.status_code == 200
        assert "forecast_requests" in r.json()

        # GET /optimization
        r = client.get("/api/admin/quota/optimization")
        assert r.status_code == 200
        assert "suggestions" in r.json()

        # GET /quota-reset
        r = client.get("/api/admin/quota/quota-reset")
        assert r.status_code == 200
        assert "reset_time" in r.json()

        # GET /downgrade-log
        r = client.get("/api/admin/quota/downgrade-log")
        assert r.status_code == 200
        assert "logs" in r.json()

        # GET /realtime-status
        r = client.get("/api/admin/quota/realtime-status")
        assert r.status_code == 200
        assert "websocket_enabled" in r.json()

        # GET /free-tier-status (both exceeded and not exceeded)
        original_data = usage_tracker._data.copy()
        today = usage_tracker._today()
        try:
            # 1. Not exceeded
            usage_tracker._data["daily"][today] = {"total": 100, "sources": {}}
            r = client.get("/api/admin/quota/free-tier-status")
            assert r.status_code == 200
            assert r.json()["exceeded"] is False
            assert r.json()["action"] == "continue"

            # 2. Exceeded
            usage_tracker._data["daily"][today] = {"total": 600, "sources": {}}
            r = client.get("/api/admin/quota/free-tier-status")
            assert r.status_code == 200
            assert r.json()["exceeded"] is True
            assert r.json()["action"] == "wait"
        finally:
            usage_tracker._data = original_data

        # GET /budget & POST /budget (valid)
        r = client.get("/api/admin/quota/budget")
        assert r.status_code == 200
        assert "monthly_limit_jpy" in r.json()


        r = client.post("/api/admin/quota/budget", json={"monthly_limit_jpy": 15000.0})
        assert r.status_code == 200
        assert r.json()["monthly_limit_jpy"] == 15000.0

    def test_additional_error_handling(self, client):
        import json
        # 1. 重複APIキー名の追加エラー
        key_name = "duplicate_key"
        api_key_1 = "abcdefghijklmn_secret_1"
        api_key_2 = "abcdefghijklmn_secret_2"
        
        # 最初の追加
        r = client.post("/api/admin/quota/key-rotation", json={
            "key_name": key_name,
            "api_key": api_key_1
        })
        assert r.status_code == 200
        
        # 重複する追加
        r = client.post("/api/admin/quota/key-rotation", json={
            "key_name": key_name,
            "api_key": api_key_2
        })
        assert r.status_code == 400
        assert "already exists" in r.json()["detail"]
        
        # クリーンアップ
        client.delete(f"/api/admin/quota/key-rotation/{key_name}")

        # 2. 閾値設定における NaN/Inf ガードレール
        r = client.post(
            "/api/admin/quota/thresholds", 
            content=json.dumps({
                "info_percent": float('nan'),
                "warning_percent": 80.0,
                "critical_percent": 95.0
            }, allow_nan=True),
            headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400
        
        r = client.post(
            "/api/admin/quota/thresholds", 
            content=json.dumps({
                "info_percent": 60.0,
                "warning_percent": float('inf'),
                "critical_percent": 95.0
            }, allow_nan=True),
            headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400

        # 3. 予算設定における NaN/Inf ガードレール
        r = client.post(
            "/api/admin/quota/budget", 
            content=json.dumps({"monthly_limit_jpy": float('nan')}, allow_nan=True),
            headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400
        
        r = client.post(
            "/api/admin/quota/budget", 
            content=json.dumps({"monthly_limit_jpy": float('inf')}, allow_nan=True),
            headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400

    def test_response_schemas(self, client):
        """APIエンドポイントの返却する辞書の主要なキー構成がdocstringで定義したものと一致することを検証"""
        # 1. /dashboard
        r = client.get("/api/admin/quota/dashboard")
        assert r.status_code == 200
        data = r.json()
        expected_dashboard_keys = {"title", "status", "usage_summary", "sections", "saving_mode", "blocked", "timestamp"}
        assert expected_dashboard_keys.issubset(data.keys())

        # 2. /status
        r = client.get("/api/admin/quota/status")
        assert r.status_code == 200
        data = r.json()
        expected_status_keys = {"status", "usage_percent", "thresholds", "description", "color"}
        assert expected_status_keys.issubset(data.keys())

        # 3. /remaining
        r = client.get("/api/admin/quota/remaining")
        assert r.status_code == 200
        data = r.json()
        expected_remaining_keys = {"remaining", "total", "percentage", "period"}
        assert expected_remaining_keys.issubset(data.keys())

        # 4. /free-tier-status
        r = client.get("/api/admin/quota/free-tier-status")
        assert r.status_code == 200
        data = r.json()
        expected_free_tier_keys = {"exceeded", "remaining_free", "free_limit", "daily_used", "action"}
        assert expected_free_tier_keys.issubset(data.keys())

        # 5. /budget
        r = client.get("/api/admin/quota/budget")
        assert r.status_code == 200
        data = r.json()
        expected_budget_keys = {"monthly_limit_jpy", "current_cost_jpy", "remaining_jpy", "exceeded"}
        assert expected_budget_keys.issubset(data.keys())


