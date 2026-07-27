import pytest
import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.admin_analytics_router import (
    router,
    _kpi_settings,
    _api_connection,
    _applied_suggestions,
    _video_data,
    _template_data,
    _smartcut_settings,
    _improvement_suggestions,
)

# FastAPIのテスト用アプリ作成
app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    """テストごとにインメモリの状態を初期化するフィクスチャ"""
    orig_kpi = copy.deepcopy(_kpi_settings)
    orig_api = copy.deepcopy(_api_connection)
    orig_applied = copy.deepcopy(_applied_suggestions)
    orig_video = copy.deepcopy(_video_data)
    orig_template = copy.deepcopy(_template_data)
    orig_smartcut = copy.deepcopy(_smartcut_settings)
    orig_suggestions = copy.deepcopy(_improvement_suggestions)

    yield

    # テスト後に状態をリストア
    _kpi_settings.clear()
    _kpi_settings.update(orig_kpi)

    _api_connection.clear()
    _api_connection.update(orig_api)

    _applied_suggestions.clear()
    _applied_suggestions.extend(orig_applied)

    _video_data.clear()
    _video_data.extend(orig_video)

    _template_data.clear()
    _template_data.extend(orig_template)

    _smartcut_settings.clear()
    _smartcut_settings.extend(orig_smartcut)

    _improvement_suggestions.clear()
    _improvement_suggestions.extend(orig_suggestions)


def test_get_analytics_dashboard():
    """GET /api/admin/analytics/dashboard のテスト"""
    # 接続中状態でのテスト
    _api_connection["connected"] = True
    response = client.get("/api/admin/analytics/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "YouTube Analytics連携"
    assert data["status"] == "connected"
    assert data["api_connected"] is True
    assert "kpi_summary" in data
    assert data["kpi_summary"]["total_videos"] == 5

    # 未接続状態でのテスト
    _api_connection["connected"] = False
    response = client.get("/api/admin/analytics/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disconnected"
    assert data["api_connected"] is False


def test_get_ctr_trend():
    """GET /api/admin/analytics/ctr-trend のテスト"""
    response = client.get("/api/admin/analytics/ctr-trend")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert len(data["history"]) == 30
    assert data["period_days"] == 30
    for item in data["history"]:
        assert "date" in item
        assert "ctr" in item
        assert 0.0 <= item["ctr"] <= 8.0


def test_get_retention_trend():
    """GET /api/admin/analytics/retention-trend のテスト"""
    response = client.get("/api/admin/analytics/retention-trend")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert len(data["history"]) == 30
    assert data["period_days"] == 30
    for item in data["history"]:
        assert "date" in item
        assert "retention" in item
        assert 0.0 <= item["retention"] <= 65.0


def test_get_video_performance():
    """GET /api/admin/analytics/video-performance のテスト"""
    response = client.get("/api/admin/analytics/video-performance")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data
    assert data["total"] == len(_video_data)
    assert len(data["videos"]) == len(_video_data)


def test_get_benchmark():
    """GET /api/admin/analytics/benchmark のテスト"""
    response = client.get("/api/admin/analytics/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert "industry_avg" in data
    assert "channel_avg" in data
    assert "comparison" in data
    assert data["comparison"]["ctr_status"] in ["above", "below"]
    assert data["comparison"]["retention_status"] in ["above", "below"]


def test_get_template_effect():
    """GET /api/admin/analytics/template-effect のテスト"""
    response = client.get("/api/admin/analytics/template-effect")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert data["total"] == len(_template_data)


def test_get_smartcut_effect():
    """GET /api/admin/analytics/smartcut-effect のテスト"""
    response = client.get("/api/admin/analytics/smartcut-effect")
    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    assert data["total"] == len(_smartcut_settings)


def test_get_ai_suggestion_effect():
    """GET /api/admin/analytics/ai-suggestion-effect のテスト"""
    response = client.get("/api/admin/analytics/ai-suggestion-effect")
    assert response.status_code == 200
    data = response.json()
    assert "adopted" in data
    assert "rejected" in data
    assert "impact_diff" in data


def test_get_chapter_effect():
    """GET /api/admin/analytics/chapter-effect のテスト"""
    response = client.get("/api/admin/analytics/chapter-effect")
    assert response.status_code == 200
    data = response.json()
    assert "with_chapters" in data
    assert "without_chapters" in data
    assert "improvement" in data


def test_get_thumbnail_effect():
    """GET /api/admin/analytics/thumbnail-effect のテスト"""
    response = client.get("/api/admin/analytics/thumbnail-effect")
    assert response.status_code == 200
    data = response.json()
    assert "thumbnails" in data
    assert "correlation_score" in data
    assert data["best_performing"] == "face_close_up"


def test_get_improvement_suggestions():
    """GET /api/admin/analytics/improvement-suggestions のテスト"""
    response = client.get("/api/admin/analytics/improvement-suggestions")
    assert response.status_code == 200
    data = response.json()
    assert "suggestions" in data
    assert data["total"] == len(_improvement_suggestions)


def test_apply_suggestion_success():
    """POST /api/admin/analytics/apply-suggestion の正常系テスト"""
    target_id = 2
    response = client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": target_id})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "applied"
    assert data["suggestion_id"] == target_id
    assert "applied_at" in data

    # 適用状態が変更されているか確認
    suggestion = next((s for s in _improvement_suggestions if s["id"] == target_id), None)
    assert suggestion is not None
    assert suggestion["applied"] is True
    assert target_id in _applied_suggestions


def test_apply_suggestion_not_found():
    """POST /api/admin/analytics/apply-suggestion の異常系テスト (404)"""
    invalid_id = 9999
    response = client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": invalid_id})
    assert response.status_code == 404
    assert response.json()["detail"] == f"Suggestion ID {invalid_id} not found"


def test_get_kpi_settings():
    """GET /api/admin/analytics/kpi-settings のテスト"""
    response = client.get("/api/admin/analytics/kpi-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["target_ctr"] == _kpi_settings["target_ctr"]
    assert data["target_retention"] == _kpi_settings["target_retention"]


def test_update_kpi_settings_success():
    """POST /api/admin/analytics/kpi-settings の正常系テスト"""
    new_settings = {"target_ctr": 6.5, "target_retention": 45.0}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["target_ctr"] == 6.5
    assert data["target_retention"] == 45.0
    assert _kpi_settings["target_ctr"] == 6.5
    assert _kpi_settings["target_retention"] == 45.0


def test_update_kpi_settings_invalid_ctr():
    """POST /api/admin/analytics/kpi-settings の異常系テスト (CTR負値)"""
    new_settings = {"target_ctr": -1.0, "target_retention": 45.0}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 400
    assert "Invalid target_ctr" in response.json()["detail"]


def test_update_kpi_settings_invalid_retention():
    """POST /api/admin/analytics/kpi-settings の異常系テスト (維持率負値)"""
    new_settings = {"target_ctr": 5.0, "target_retention": -2.5}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 400
    assert "Invalid target_retention" in response.json()["detail"]


def test_get_kpi_achievement():
    """GET /api/admin/analytics/kpi-achievement のテスト"""
    # 正常な目標値での達成率計算の検証
    _kpi_settings["target_ctr"] = 5.0
    _kpi_settings["target_retention"] = 50.0
    response = client.get("/api/admin/analytics/kpi-achievement")
    assert response.status_code == 200
    data = response.json()
    assert "target" in data
    assert "actual" in data
    assert "achievement_rate" in data
    assert "ctr" in data["achievement_rate"]
    assert "retention" in data["achievement_rate"]
    assert "overall" in data["achievement_rate"]

    # 目標が0に設定された場合のゼロ除算回避ロジック（境界値テスト）
    _kpi_settings["target_ctr"] = 0.0
    _kpi_settings["target_retention"] = 0.0
    response = client.get("/api/admin/analytics/kpi-achievement")
    assert response.status_code == 200
    data = response.json()
    assert data["achievement_rate"]["ctr"] == 100.0
    assert data["achievement_rate"]["retention"] == 100.0


def test_get_trend_analysis():
    """GET /api/admin/analytics/trend-analysis のテスト"""
    response = client.get("/api/admin/analytics/trend-analysis")
    assert response.status_code == 200
    data = response.json()
    assert "trends" in data
    assert data["total"] == 4


def test_get_competitor_analysis():
    """GET /api/admin/analytics/competitor-analysis のテスト"""
    response = client.get("/api/admin/analytics/competitor-analysis")
    assert response.status_code == 200
    data = response.json()
    assert "competitors" in data
    assert data["our_rank"] == 2
    assert data["total_compared"] == 3


def test_generate_report_success():
    """POST /api/admin/analytics/generate-report の正常系テスト"""
    # weekly
    response = client.post("/api/admin/analytics/generate-report", json={"period": "weekly"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "generated"
    assert data["period"] == "weekly"
    assert "download/report_weekly.pdf" in data["download_url"]

    # monthly
    response = client.post("/api/admin/analytics/generate-report", json={"period": "monthly"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "generated"
    assert data["period"] == "monthly"
    assert "download/report_monthly.pdf" in data["download_url"]


def test_generate_report_invalid_period():
    """POST /api/admin/analytics/generate-report の異常系テスト (無効な期間)"""
    response = client.post("/api/admin/analytics/generate-report", json={"period": "yearly"})
    assert response.status_code == 400
    assert "Invalid period" in response.json()["detail"]


def test_get_api_connection():
    """GET /api/admin/analytics/api-connection のテスト"""
    response = client.get("/api/admin/analytics/api-connection")
    assert response.status_code == 200
    data = response.json()
    assert data["update_interval_minutes"] == _api_connection["update_interval_minutes"]
    assert data["enabled"] == _api_connection["enabled"]


def test_update_api_connection():
    """POST /api/admin/analytics/api-connection のテスト"""
    new_conn = {"update_interval_minutes": 120, "enabled": False}
    response = client.post("/api/admin/analytics/api-connection", json=new_conn)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["update_interval_minutes"] == 120
    assert data["enabled"] is False
    assert _api_connection["update_interval_minutes"] == 120
    assert _api_connection["enabled"] is False


def test_get_cache_fallback():
    """GET /api/admin/analytics/cache-fallback のテスト"""
    # API接続中の状態
    _api_connection["connected"] = True
    response = client.get("/api/admin/analytics/cache-fallback")
    assert response.status_code == 200
    data = response.json()
    assert data["cache_available"] is True
    assert data["fallback_active"] is False
    assert data["data_freshness"] == "fresh"

    # API未接続の状態（フォールバック活性化）
    _api_connection["connected"] = False
    response = client.get("/api/admin/analytics/cache-fallback")
    assert response.status_code == 200
    data = response.json()
    assert data["fallback_active"] is True
    assert data["data_freshness"] == "cached"


def test_get_owner_dashboard():
    """GET /api/admin/analytics/owner-dashboard のテスト"""
    response = client.get("/api/admin/analytics/owner-dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "highlights" in data
    assert len(data["highlights"]) == 3


def test_get_period_comparison():
    """GET /api/admin/analytics/period-comparison のテスト"""
    # デフォルトパラメータ
    response = client.get("/api/admin/analytics/period-comparison")
    assert response.status_code == 200
    data = response.json()
    assert data["period1"]["label"] == "2026-03"
    assert data["period2"]["label"] == "2026-04"
    assert "diff" in data

    # パラメータ指定あり
    response = client.get("/api/admin/analytics/period-comparison?period1=2026-01&period2=2026-02")
    assert response.status_code == 200
    data = response.json()
    assert data["period1"]["label"] == "2026-01"
    assert data["period2"]["label"] == "2026-02"


def test_get_growth_forecast():
    """GET /api/admin/analytics/growth-forecast のテスト"""
    response = client.get("/api/admin/analytics/growth-forecast")
    assert response.status_code == 200
    data = response.json()
    assert "forecast_subscribers" in data
    assert "forecast_views" in data
    assert "growth_rate" in data
    assert data["confidence"] == 0.82


def test_update_kpi_settings_validation_error():
    """POST /api/admin/analytics/kpi-settings のバリデーションエラーテスト (422)"""
    response = client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": "invalid_number", "target_retention": 45.0})
    assert response.status_code == 422


def test_update_api_connection_validation_error():
    """POST /api/admin/analytics/api-connection のバリデーションエラーテスト (422)"""
    response = client.post("/api/admin/analytics/api-connection", json={"update_interval_minutes": "not_an_int", "enabled": True})
    assert response.status_code == 422


def test_generate_report_validation_error():
    """POST /api/admin/analytics/generate-report のバリデーションエラーテスト (422)"""
    response = client.post("/api/admin/analytics/generate-report", json={"period": {"invalid": "type"}})
    assert response.status_code == 422


def test_get_period_comparison_edge_cases():
    """GET /api/admin/analytics/period-comparison の特殊パラメータ値テスト"""
    special_period = "2026-04-special-!@#$%"
    response = client.get(
        "/api/admin/analytics/period-comparison",
        params={"period1": special_period, "period2": "2026-05"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["period1"]["label"] == special_period
