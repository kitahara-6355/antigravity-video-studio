import sys
import os
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routers.admin_quality_router import router, _test_results

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)

def test_dashboard_healthy(client):
    original_failed = _test_results["failed"]
    try:
        _test_results["failed"] = 5
        response = client.get("/api/admin/quality/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "CI/CD" in data["title"]
        assert data["status"] == "healthy"
        assert "sections" in data
    finally:
        _test_results["failed"] = original_failed

def test_dashboard_degraded(client):
    original_failed = _test_results["failed"]
    try:
        _test_results["failed"] = 15
        response = client.get("/api/admin/quality/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
    finally:
        _test_results["failed"] = original_failed

def test_test_results(client):
    response = client.get("/api/admin/quality/test-results")
    assert response.status_code == 200
    assert response.json()["passed"] == 2064

def test_coverage(client):
    response = client.get("/api/admin/quality/coverage")
    assert response.status_code == 200
    assert response.json()["branch_pct"] == 72.0

def test_coverage_trend(client):
    response = client.get("/api/admin/quality/coverage-trend")
    assert response.status_code == 200
    data = response.json()
    assert "history" in data
    assert data["period_days"] == 30

def test_fitness(client):
    response = client.get("/api/admin/quality/fitness")
    assert response.status_code == 200
    assert response.json()["passed"] == 26

def test_ratchet(client):
    """**実体に繋がっていること**を見る（R1.5-C4）。

    ここは以前 `valid is True` を期待していたが、それが通っていたのは
    ルータが `total_items: 770 / pass_items: 770 / correlation_rate: 100.0`
    という**作り物**を返していたから。リポジトリにある実測
    （`snapshots/v8_baseline.json`）は pass 75 / fail 16 / skip 954 で、
    `valid` は False になる。**健全だと言い張るテストをやめて、
    出所が実体であることを固定する。**
    """
    response = client.get("/api/admin/quality/ratchet")
    assert response.status_code == 200
    data = response.json()
    assert data["data_source"] == "derived"
    assert data["source"] == "backend/ux_verification/snapshots/v8_baseline.json"
    assert data["total_items"] == (
        data["pass_items"] + data["fail_items"] + data["skip_items"]
    )
    assert data["valid"] is (data["fail_items"] == 0)

def test_fv(client):
    response = client.get("/api/admin/quality/fv")
    assert response.status_code == 200
    assert response.json()["passed"] == 18

def test_e2e(client):
    response = client.get("/api/admin/quality/e2e")
    assert response.status_code == 200
    assert response.json()["passed"] == 55

def test_quality_gates(client):
    response = client.get("/api/admin/quality/quality-gates")
    assert response.status_code == 200

def test_vision_gap(client):
    response = client.get("/api/admin/quality/vision-gap")
    assert response.status_code == 200

def test_quality_trend(client):
    response = client.get("/api/admin/quality/quality-trend")
    assert response.status_code == 200
    assert len(response.json()["history"]) == 30

def test_failure_analysis(client):
    response = client.get("/api/admin/quality/failure-analysis")
    assert response.status_code == 200

def test_run_tests_success(client):
    response = client.post("/api/admin/quality/run-tests", json={"suite": "unit"})
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert response.json()["estimated_duration_seconds"] == 30

    response_all = client.post("/api/admin/quality/run-tests", json={"suite": "all"})
    assert response_all.status_code == 200
    assert response_all.json()["estimated_duration_seconds"] == 180

def test_run_tests_invalid(client):
    response = client.post("/api/admin/quality/run-tests", json={"suite": "invalid"})
    assert response.status_code == 400
    assert "Invalid suite" in response.json()["detail"]

def test_generate_report_success(client):
    response = client.post("/api/admin/quality/generate-report", json={"format": "html"})
    assert response.status_code == 200
    assert response.json()["status"] == "generated"

def test_generate_report_invalid(client):
    response = client.post("/api/admin/quality/generate-report", json={"format": "txt"})
    assert response.status_code == 400
    assert "Invalid format" in response.json()["detail"]

def test_lint(client):
    response = client.get("/api/admin/quality/lint")
    assert response.status_code == 200

def test_security(client):
    response = client.get("/api/admin/quality/security")
    assert response.status_code == 200

def test_deploy(client):
    response = client.get("/api/admin/quality/deploy")
    assert response.status_code == 200

def test_rollback(client):
    response = client.post("/api/admin/quality/rollback", json={"target_version": "3.5.0"})
    assert response.status_code == 200
    assert response.json()["status"] == "rolled_back"

def test_changelog(client):
    response = client.get("/api/admin/quality/changelog")
    assert response.status_code == 200

def test_quality_settings(client):
    response = client.get("/api/admin/quality/quality-settings")
    assert response.status_code == 200
    
    response_post = client.post("/api/admin/quality/quality-settings", json={"coverage_threshold": 80.0, "tests_required": False})
    assert response_post.status_code == 200
    assert response_post.json()["coverage_threshold"] == 80.0
    
    response_low = client.post("/api/admin/quality/quality-settings", json={"coverage_threshold": -1.0})
    assert response_low.status_code == 400
    
    response_high = client.post("/api/admin/quality/quality-settings", json={"coverage_threshold": 101.0})
    assert response_high.status_code == 400

def test_notifications(client):
    response = client.get("/api/admin/quality/notifications")
    assert response.status_code == 200
    
    response_post = client.post("/api/admin/quality/notifications", json={"channels": ["email"], "enabled": False})
    assert response_post.status_code == 200
    assert response_post.json()["enabled"] is False

def test_quick_fixes(client):
    response = client.get("/api/admin/quality/quick-fixes")
    assert response.status_code == 200
    assert "fixes" in response.json()

def test_apply_quick_fix_success(client):
    response = client.post("/api/admin/quality/quick-fix", json={"fix_id": 1})
    assert response.status_code == 200
    assert response.json()["status"] == "applied"

def test_apply_quick_fix_not_found(client):
    response = client.post("/api/admin/quality/quick-fix", json={"fix_id": 999})
    assert response.status_code == 404

def test_dashboard_timestamp_exists(client):
    response = client.get("/api/admin/quality/dashboard")
    assert response.status_code == 200
    assert "timestamp" in response.json()


def test_rollback_invalid_format(client):
    # ロールバックのバージョン形式が不正な場合、400エラーが返ることを検証
    response = client.post("/api/admin/quality/rollback", json={"target_version": "invalid_version"})
    assert response.status_code == 400
    assert "Invalid target_version format" in response.json()["detail"]

def test_notifications_empty_channels(client):
    # 通知チャンネルが空の場合、400エラーが返ることを検証
    response = client.post("/api/admin/quality/notifications", json={"channels": [], "enabled": True})
    assert response.status_code == 400
    assert "channels cannot be empty" in response.json()["detail"]

def test_apply_quick_fix_negative_id(client):
    # fix_id が負の数の場合、400エラーが返ることを検証
    response = client.post("/api/admin/quality/quick-fix", json={"fix_id": -5})
    assert response.status_code == 400
    assert "must be a non-negative integer" in response.json()["detail"]

def test_dashboard_exception_handling(client):
    # 内部エラー発生時に 500 エラーが返ることを検証
    from routers.admin_quality_router import _test_results
    original_results = dict(_test_results)
    try:
        _test_results.clear()
        response = client.get("/api/admin/quality/dashboard")
        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]
    finally:
        _test_results.update(original_results)


def test_dashboard_key_error_handling_specific(client):
    # KeyError が発生した際、詳細メッセージに "Internal server error" が含まれることを検証
    from routers.admin_quality_router import _test_results
    original_results = dict(_test_results)
    try:
        if "failed" in _test_results:
            del _test_results["failed"]
        response = client.get("/api/admin/quality/dashboard")
        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]
    finally:
        _test_results.clear()
        _test_results.update(original_results)


# ── R1.5-C4: 数字は出所を名乗る ────────────────────────────────────────
#
# 憲法 §7.3.2 の A-4「push時にテスト/リント/セキュリティが自動実行」は
# **実際に動いている**（GitHub Actions）のに、この画面は全部定数だった。
# 出所は3段しかない — `measured` / `derived` / `sample`。
# 実体がリポジトリにあるものは繋ぎ、無いものは作り物だと名乗る。


def test_全エンドポイントが出所を名乗る(client):
    """**この router の応答は1つ残らず出所を名乗る**（R1.5-C4）。

    `admin_analytics_router` / `admin_channel_router` と同じ形の総当たり。
    **新しい経路を足して出所を書き忘れたらここで落ちる。**
    5周連続で落ちた原因が「同じクラスの別経路の見落とし」なので、
    人が25回思い出すのではなく、機械が数える側に置く。
    """
    from routers.admin_quality_router import router

    許す出所 = {"measured", "derived", "sample"}
    印なし = []
    for route in router.routes:
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            body = {"suite": "all", "format": "html", "target_version": "3.5.0",
                    "coverage_threshold": 70.0, "tests_required": True,
                    "channels": ["slack"], "enabled": True, "fix_id": 1}
            resp = (client.get(route.path) if method == "GET"
                    else client.post(route.path, json=body))
            if resp.status_code != 200:
                印なし.append((method, route.path, resp.status_code))
                continue
            payload = resp.json()
            if not isinstance(payload, dict) or payload.get("data_source") not in 許す出所:
                印なし.append((method, route.path, str(payload)[:120]))

    assert not 印なし, 印なし


def test_実体があるものは実データに繋がっている(client):
    """**繋げるものを作り物のまま置かない**（R1.5-C4）。

    リポジトリの中に実データがあるのに定数を返していた3経路。
    繋いだ結果、**作り物と実体が食い違っていることが分かった**:

    | 経路 | 作り物 | 実体 |
    |---|---|---|
    | `/ratchet` | 770/770・連動率 100.0% | pass 75 / fail 16 / skip 954 |
    | `/lint` | issues 2件 | 28,842件（W293 が 27,393件）|
    | `/vision-gap` | score 60.35（独自の定数）| 65.95（正典）|

    `/vision-gap` がとくに悪い。**現在地の正典は
    `vision_backlog.json`**（憲法第5条）なのに、画面が別の数字を
    持っていた。台帳が2つあると、どちらが本当か分からなくなる。
    """
    for path, source in [
        ("/api/admin/quality/ratchet",
         "backend/ux_verification/snapshots/v8_baseline.json"),
        ("/api/admin/quality/lint", ".github/ruff-baseline.json"),
        ("/api/admin/quality/vision-gap", "backend/branding/vision_backlog.json"),
    ]:
        data = client.get(path).json()
        assert data["data_source"] == "derived", path
        assert data["is_real"] is True, path
        assert data["source"] == source, path


def test_正典と画面の実現度が一致する(client):
    """**現在地は1つ**（憲法第5条・R1.5-C4）。"""
    import json
    from pathlib import Path

    正典 = json.loads(
        (Path(__file__).resolve().parent.parent.parent
         / "backend/branding/vision_backlog.json").read_text(encoding="utf-8")
    )
    画面 = client.get("/api/admin/quality/vision-gap").json()

    assert 画面["score"] == 正典["vision_realization_score"]
    assert 画面["last_audit_date"] == 正典["last_audit_date"]
