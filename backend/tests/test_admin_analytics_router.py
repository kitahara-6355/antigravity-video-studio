import sys
import types
import os

# ワークツリーのルートと backend を sys.path に追加する
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
root_dir = os.path.dirname(backend_dir)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# routersパッケージの__init__.pyがロードされるのを防ぐためのダミーモジュール登録
# これにより、不要なルーターの依存関係（soul_routerやwebsocket_routerなど）によるロードエラーを回避します。
if 'routers' not in sys.modules:
    routers_mod = types.ModuleType('routers')
    routers_mod.__path__ = [os.path.join(backend_dir, "routers")]
    sys.modules['routers'] = routers_mod

import pytest
import copy


@pytest.fixture(name="client")
def client_fixture():
    """FastAPI TestClient を提供するフィクスチャ"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.admin_analytics_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    """テストごとにインメモリの状態を初期化するフィクスチャ"""
    from routers.admin_analytics_router import (
        _kpi_settings,
        _api_connection,
        _applied_suggestions,
        _video_data,
        _template_data,
        _smartcut_settings,
        _improvement_suggestions,
    )

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


def test_get_analytics_dashboard(client):
    """GET /api/admin/analytics/dashboard のテスト"""
    from routers.admin_analytics_router import _api_connection, _video_data

    # 接続中状態でのテスト
    _api_connection["connected"] = True
    response = client.get("/api/admin/analytics/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "YouTube Analytics連携"
    assert data["status"] == "connected"
    assert data["api_connected"] is True
    assert "kpi_summary" in data
    assert data["kpi_summary"]["total_videos"] == len(_video_data)

    # 未接続状態でのテスト
    _api_connection["connected"] = False
    response = client.get("/api/admin/analytics/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disconnected"
    assert data["api_connected"] is False


def test_get_ctr_trend(client):
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


def test_get_retention_trend(client):
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


def test_get_video_performance(client):
    """GET /api/admin/analytics/video-performance のテスト"""
    from routers.admin_analytics_router import _video_data

    response = client.get("/api/admin/analytics/video-performance")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data
    assert data["total"] == len(_video_data)
    assert len(data["videos"]) == len(_video_data)


def test_get_benchmark(client):
    """GET /api/admin/analytics/benchmark のテスト"""
    response = client.get("/api/admin/analytics/benchmark")
    assert response.status_code == 200
    data = response.json()
    assert "industry_avg" in data
    assert "channel_avg" in data
    assert "comparison" in data
    assert data["comparison"]["ctr_status"] in ["above", "below"]
    assert data["comparison"]["retention_status"] in ["above", "below"]


def test_get_template_effect(client):
    """GET /api/admin/analytics/template-effect のテスト"""
    from routers.admin_analytics_router import _template_data

    response = client.get("/api/admin/analytics/template-effect")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert data["total"] == len(_template_data)


def test_get_smartcut_effect(client):
    """GET /api/admin/analytics/smartcut-effect のテスト"""
    from routers.admin_analytics_router import _smartcut_settings

    response = client.get("/api/admin/analytics/smartcut-effect")
    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    assert data["total"] == len(_smartcut_settings)


def test_get_ai_suggestion_effect(client):
    """GET /api/admin/analytics/ai-suggestion-effect のテスト"""
    response = client.get("/api/admin/analytics/ai-suggestion-effect")
    assert response.status_code == 200
    data = response.json()
    assert "adopted" in data
    assert "rejected" in data
    assert "impact_diff" in data


def test_get_chapter_effect(client):
    """GET /api/admin/analytics/chapter-effect のテスト"""
    response = client.get("/api/admin/analytics/chapter-effect")
    assert response.status_code == 200
    data = response.json()
    assert "with_chapters" in data
    assert "without_chapters" in data
    assert "improvement" in data


def test_get_thumbnail_effect(client):
    """GET /api/admin/analytics/thumbnail-effect のテスト"""
    response = client.get("/api/admin/analytics/thumbnail-effect")
    assert response.status_code == 200
    data = response.json()
    assert "thumbnails" in data
    assert "correlation_score" in data
    assert data["best_performing"] == "face_close_up"


def test_get_improvement_suggestions(client):
    """GET /api/admin/analytics/improvement-suggestions のテスト"""
    from routers.admin_analytics_router import _improvement_suggestions

    response = client.get("/api/admin/analytics/improvement-suggestions")
    assert response.status_code == 200
    data = response.json()
    assert "suggestions" in data
    assert data["total"] == len(_improvement_suggestions)


def test_apply_suggestion_success(client):
    """POST /api/admin/analytics/apply-suggestion の正常系テスト"""
    from routers.admin_analytics_router import (
        _improvement_suggestions,
        _applied_suggestions,
    )

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


def test_apply_suggestion_not_found(client):
    """POST /api/admin/analytics/apply-suggestion の異常系テスト (404)"""
    invalid_id = 9999
    response = client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": invalid_id})
    assert response.status_code == 404
    assert response.json()["detail"] == f"Suggestion ID {invalid_id} not found"


def test_get_kpi_settings(client):
    """GET /api/admin/analytics/kpi-settings のテスト"""
    from routers.admin_analytics_router import _kpi_settings

    response = client.get("/api/admin/analytics/kpi-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["target_ctr"] == _kpi_settings["target_ctr"]
    assert data["target_retention"] == _kpi_settings["target_retention"]


def test_update_kpi_settings_success(client):
    """POST /api/admin/analytics/kpi-settings の正常系テスト"""
    from routers.admin_analytics_router import _kpi_settings

    new_settings = {"target_ctr": 6.5, "target_retention": 45.0}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["target_ctr"] == 6.5
    assert data["target_retention"] == 45.0
    assert _kpi_settings["target_ctr"] == 6.5
    assert _kpi_settings["target_retention"] == 45.0


def test_update_kpi_settings_invalid_ctr(client):
    """POST /api/admin/analytics/kpi-settings の異常系テスト (CTR負値)"""
    new_settings = {"target_ctr": -1.0, "target_retention": 45.0}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 400
    assert "Invalid target_ctr" in response.json()["detail"]


def test_update_kpi_settings_invalid_retention(client):
    """POST /api/admin/analytics/kpi-settings の異常系テスト (維持率負値)"""
    new_settings = {"target_ctr": 5.0, "target_retention": -2.5}
    response = client.post("/api/admin/analytics/kpi-settings", json=new_settings)
    assert response.status_code == 400
    assert "Invalid target_retention" in response.json()["detail"]


def test_get_kpi_achievement(client):
    """GET /api/admin/analytics/kpi-achievement のテスト"""
    from routers.admin_analytics_router import _kpi_settings

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


def test_get_trend_analysis(client):
    """GET /api/admin/analytics/trend-analysis のテスト"""
    response = client.get("/api/admin/analytics/trend-analysis")
    assert response.status_code == 200
    data = response.json()
    assert "trends" in data
    assert data["total"] == 4


def test_get_competitor_analysis(client):
    """GET /api/admin/analytics/competitor-analysis のテスト"""
    response = client.get("/api/admin/analytics/competitor-analysis")
    assert response.status_code == 200
    data = response.json()
    assert "competitors" in data
    assert data["our_rank"] == 2
    assert data["total_compared"] == 3


def test_generate_report_success(client):
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


def test_generate_report_invalid_period(client):
    """POST /api/admin/analytics/generate-report の異常系テスト (無効な期間)"""
    response = client.post("/api/admin/analytics/generate-report", json={"period": "yearly"})
    assert response.status_code == 400
    assert "Invalid period" in response.json()["detail"]


def test_get_api_connection(client):
    """GET /api/admin/analytics/api-connection のテスト"""
    from routers.admin_analytics_router import _api_connection

    response = client.get("/api/admin/analytics/api-connection")
    assert response.status_code == 200
    data = response.json()
    assert data["update_interval_minutes"] == _api_connection["update_interval_minutes"]
    assert data["enabled"] == _api_connection["enabled"]


def test_update_api_connection(client):
    """POST /api/admin/analytics/api-connection のテスト"""
    from routers.admin_analytics_router import _api_connection

    new_conn = {"update_interval_minutes": 120, "enabled": False}
    response = client.post("/api/admin/analytics/api-connection", json=new_conn)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["update_interval_minutes"] == 120
    assert data["enabled"] is False
    assert _api_connection["update_interval_minutes"] == 120
    assert _api_connection["enabled"] is False


def test_get_cache_fallback(client):
    """GET /api/admin/analytics/cache-fallback のテスト"""
    from routers.admin_analytics_router import _api_connection

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


def test_get_owner_dashboard(client):
    """GET /api/admin/analytics/owner-dashboard のテスト"""
    response = client.get("/api/admin/analytics/owner-dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "highlights" in data
    assert len(data["highlights"]) == 3


def test_get_period_comparison(client):
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


def test_get_growth_forecast(client):
    """GET /api/admin/analytics/growth-forecast のテスト"""
    response = client.get("/api/admin/analytics/growth-forecast")
    assert response.status_code == 200
    data = response.json()
    assert "forecast_subscribers" in data
    assert "forecast_views" in data
    assert "growth_rate" in data
    assert data["confidence"] == 0.82


def test_video_data_empty_zero_division(client):
    """_video_data が空のときにゼロ除算が発生しないことを確認するテスト"""
    from routers.admin_analytics_router import _video_data

    # _video_data を一時的に空にする
    original_video_data = list(_video_data)
    _video_data.clear()

    try:
        # 1. /dashboard
        response = client.get("/api/admin/analytics/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["kpi_summary"]["avg_ctr"] == 0.0
        assert data["kpi_summary"]["avg_retention"] == 0.0

        # 2. /benchmark
        response = client.get("/api/admin/analytics/benchmark")
        assert response.status_code == 200
        data = response.json()
        assert data["channel_avg"]["ctr"] == 0.0
        assert data["channel_avg"]["retention"] == 0.0

        # 3. /kpi-achievement
        response = client.get("/api/admin/analytics/kpi-achievement")
        assert response.status_code == 200
        data = response.json()
        assert data["actual"]["ctr"] == 0.0
        assert data["actual"]["retention"] == 0.0

        # 4. /owner-dashboard
        response = client.get("/api/admin/analytics/owner-dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["avg_ctr"] == 0.0
        assert data["summary"]["avg_retention"] == 0.0

    finally:
        # データを復元
        _video_data.extend(original_video_data)



def test_update_kpi_settings_invalid_ctr_upper_bound(client):
    """POST /api/admin/analytics/kpi-settings CTR目標の上限値(100.0)エラーのテスト"""
    response = client.post(
        "/api/admin/analytics/kpi-settings",
        json={"target_ctr": 101.0, "target_retention": 50.0}
    )
    assert response.status_code == 400
    assert "Must be 100.0 or less" in response.json()["detail"]


def test_update_kpi_settings_invalid_retention_upper_bound(client):
    """POST /api/admin/analytics/kpi-settings 維持率目標の上限値(100.0)エラーのテスト"""
    response = client.post(
        "/api/admin/analytics/kpi-settings",
        json={"target_ctr": 5.0, "target_retention": 101.0}
    )
    assert response.status_code == 400
    assert "Must be 100.0 or less" in response.json()["detail"]


def test_get_period_comparison_invalid_format(client):
    """GET /api/admin/analytics/period-comparison パラメータフォーマットエラーのテスト"""
    # period1が不正な場合
    response = client.get("/api/admin/analytics/period-comparison?period1=2026-13&period2=2026-04")
    assert response.status_code == 400
    assert "Invalid period format" in response.json()["detail"]

    # period2が不正な場合
    response = client.get("/api/admin/analytics/period-comparison?period1=2026-03&period2=invalid")
    assert response.status_code == 400
    assert "Invalid period format" in response.json()["detail"]


def test_unexpected_exception_logging(client):
    """例外発生時にHTTP 500となりログ出力されることを確認するテスト"""
    from unittest.mock import patch

    # get_analytics_dashboardで例外が発生するようにモックする
    with patch("routers.admin_analytics_router._video_data", new=None):
        response = client.get("/api/admin/analytics/dashboard")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_get_analytics_dashboard_http_exception(client):
    """GET /api/admin/analytics/dashboard で HTTPException が発生した際の挙動テスト"""
    from unittest.mock import patch
    from fastapi import HTTPException
    with patch("builtins.sum", side_effect=HTTPException(status_code=400, detail="Mocked HTTPException")):
        response = client.get("/api/admin/analytics/dashboard")
        assert response.status_code == 400
        assert response.json()["detail"] == "Mocked HTTPException"


def test_get_benchmark_exceptions(client):
    """GET /api/admin/analytics/benchmark で例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    from fastapi import HTTPException
    # HTTPException (196-197)
    with patch("builtins.sum", side_effect=HTTPException(status_code=402, detail="Mocked Payment Required")):
        response = client.get("/api/admin/analytics/benchmark")
        assert response.status_code == 402
        assert response.json()["detail"] == "Mocked Payment Required"
    # General Exception (198-200)
    with patch("builtins.sum", side_effect=ValueError("Mocked value error")):
        response = client.get("/api/admin/analytics/benchmark")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_apply_suggestion_unexpected_exception(client):
    """POST /api/admin/analytics/apply-suggestion で一般例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    with patch("routers.admin_analytics_router._improvement_suggestions", new=None):
        response = client.post("/api/admin/analytics/apply-suggestion", json={"suggestion_id": 1})
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_update_kpi_settings_unexpected_exception(client):
    """POST /api/admin/analytics/kpi-settings で一般例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    with patch("routers.admin_analytics_router._kpi_settings", new=None):
        response = client.post("/api/admin/analytics/kpi-settings", json={"target_ctr": 5.0, "target_retention": 50.0})
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_get_kpi_achievement_exceptions(client):
    """GET /api/admin/analytics/kpi-achievement で例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    from fastapi import HTTPException
    # HTTPException (361-362)
    with patch("builtins.sum", side_effect=HTTPException(status_code=403, detail="Mocked Forbidden")):
        response = client.get("/api/admin/analytics/kpi-achievement")
        assert response.status_code == 403
        assert response.json()["detail"] == "Mocked Forbidden"
    # General Exception (363-365)
    with patch("builtins.sum", side_effect=ValueError("Mocked value error")):
        response = client.get("/api/admin/analytics/kpi-achievement")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_generate_report_unexpected_exception(client):
    """POST /api/admin/analytics/generate-report で一般例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    with patch("routers.admin_analytics_router.datetime") as mock_datetime:
        mock_datetime.now.side_effect = ValueError("Mocked datetime error")
        response = client.post("/api/admin/analytics/generate-report", json={"period": "weekly"})
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"


def test_get_period_comparison_unexpected_exception(client):
    """GET /api/admin/analytics/period-comparison で一般例外が発生した際の挙動テスト"""
    from unittest.mock import patch
    with patch("routers.admin_analytics_router.validate_period_format", side_effect=ValueError("Mocked format error")):
        response = client.get("/api/admin/analytics/period-comparison")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"



def test_specific_exceptions_caught(client):
    """KeyError, TypeError, ValueError はキャッチされて 500 になることを確認"""
    from unittest.mock import patch
    
    # KeyError
    with patch("routers.admin_analytics_router._calculate_average_metrics", side_effect=KeyError("Mocked KeyError")):
        response = client.get("/api/admin/analytics/dashboard")
        assert response.status_code == 500
        
    # ValueError
    with patch("routers.admin_analytics_router._calculate_average_metrics", side_effect=ValueError("Mocked ValueError")):
        response = client.get("/api/admin/analytics/dashboard")
        assert response.status_code == 500

def test_unhandled_exception_bubbles_up(client):
    """RuntimeError などの対象外の例外はルータでキャッチされず上に抜けることを確認"""
    from unittest.mock import patch
    
    with patch("routers.admin_analytics_router._calculate_average_metrics", side_effect=RuntimeError("Unhandled RuntimeError")):
        with pytest.raises(RuntimeError):
            client.get("/api/admin/analytics/dashboard")


# ── R1.5-C4: 固定値に必ず印が付いていること ────────────────────────────────
#
# `admin_channel_router` で直したのと同じ偽の success が、**1ファイル隣に
# そのまま残っていた**（gate-verifier 4周目の指摘 C-6）:
#   - `connected: True` + 現在時刻の `last_sync`（一度も接続していないのに）
#   - `/retention-trend` が式で合成した30日分の維持率
#   - `/chapter-effect` が固定の視聴時間
# `grep -c is_real` は 0 件だった。


def test_全エンドポイントが固定値の印を返す(client):
    """**この router の応答は1つ残らず「実在の数字ではない」と名乗る**（R1.5-C4）。

    YouTube Analytics には一度も接続していない。`_video_data` も
    `_template_data` も `/retention-trend` の30日分も作り物で、
    収益化の到達度をこの数字で判断すると嘘になる。
    **新しい経路を足して印を忘れたらここで落ちる。**
    """
    from routers.admin_analytics_router import router

    印なし = []
    for route in router.routes:
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            body = {"suggestion_id": 1, "period": "monthly",
                    "update_interval_minutes": 60, "enabled": True,
                    "target_ctr": 5.0, "target_retention": 50.0}
            resp = (client.get(route.path) if method == "GET"
                    else client.post(route.path, json=body))
            if resp.status_code != 200:
                印なし.append((method, route.path, resp.status_code))
                continue
            payload = resp.json()
            if not isinstance(payload, dict) or payload.get("is_real") is not False:
                印なし.append((method, route.path, str(payload)[:120]))

    assert not 印なし, 印なし


def test_接続していないので接続済みと名乗らない(client):
    """**現在時刻の `last_sync` を返さない**（R1.5-C4）。

    設定を書き換えただけで `last_sync` に現在時刻を入れていたので、
    設定画面を開くだけで「いま同期した」ように見えていた。
    """
    from routers.admin_analytics_router import _api_connection

    assert _api_connection["connected"] is False
    assert _api_connection["last_sync"] is None

    data = client.get("/api/admin/analytics/api-connection").json()
    assert data["connected"] is False
    assert data["last_sync"] is None
    assert data["is_real"] is False

    # 設定の更新では「同期した」ことにならない
    client.post("/api/admin/analytics/api-connection",
                json={"update_interval_minutes": 30, "enabled": True})
    assert _api_connection["last_sync"] is None
    assert client.get("/api/admin/analytics/cache-fallback").json()[
        "last_successful_sync"] is None


def test_合成した維持率にも印が付く(client):
    """`/retention-trend` は式で組み立てた30日分を返す（実測ではない）。"""
    data = client.get("/api/admin/analytics/retention-trend").json()

    assert data["is_real"] is False
    assert data["data_source"] == "sample"
    assert len(data["history"]) == 30
