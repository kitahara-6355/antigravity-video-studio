import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
import json
import sqlite3
import asyncio
import importlib

# usage_router をインポート
from routers.usage_router import (
    router,
    thumbnail_router,
    _get_tier_label,
    _get_alert_message,
    _get_retry_advice,
    _get_wait_recommendations
)

# テスト用のFastAPIアプリ
app = FastAPI()
app.include_router(router)
app.include_router(thumbnail_router)
client = TestClient(app)

# ------------------------------------------------------------
# 1. ヘルパー関数のテスト
# ------------------------------------------------------------

def test_get_tier_label_success():
    """_get_tier_label が正常にモデル_configからティアを取得できることのテスト"""
    mock_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-2.5-pro", "label": "Pro Tier"},
                "standard": {"model": "gemini-2.5-flash", "label": "Flash Tier"}
            }
        }
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_config))):
        label = _get_tier_label("gemini-2.5-pro")
        assert label == "Pro Tier"

def test_get_tier_label_unknown():
    """モデルが存在しない場合に _get_tier_label が Unknown を返すことのテスト"""
    mock_config = {
        "text_generation": {
            "tiers": {}
        }
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_config))):
        label = _get_tier_label("non-existent")
        assert label == "Unknown"

def test_get_tier_label_exception():
    """例外発生時に _get_tier_label が Unknown を返すことのテスト"""
    with patch("builtins.open", side_effect=Exception("Read error")):
        label = _get_tier_label("gemini-2.5-pro")
        assert label == "Unknown"

def test_get_tier_label_http_exception():
    """HTTPException はそのまま伝播することのテスト"""
    with patch("builtins.open", side_effect=HTTPException(status_code=400, detail="HTTP error")):
        with pytest.raises(HTTPException):
            _get_tier_label("gemini-2.5-pro")

def test_get_alert_message():
    """_get_alert_message が正しくメッセージを生成することのテスト"""
    assert _get_alert_message("model1", {"alert_level": "critical", "remaining": 0}) == "model1の日次枠を使い切りました。翌日まで使用できません。"
    assert _get_alert_message("model1", {"alert_level": "block", "remaining": 5}) == "model1の残り枠が5件です。処理がブロックされます。"
    assert _get_alert_message("model1", {"alert_level": "warning", "remaining": 10}) == "model1の残り枠が10件です。使用を控えてください。"
    assert _get_alert_message("model1", {"alert_level": "normal", "remaining": 50}) == ""

def test_get_retry_advice():
    """_get_retry_advice の閾値判定のテスト"""
    assert "慎重に" in _get_retry_advice(4, 10)
    assert "注意しながら" in _get_retry_advice(15, 10)
    assert "十分な余裕" in _get_retry_advice(25, 10)

def test_get_wait_recommendations_logic():
    """_get_wait_recommendations の各分岐のテスト"""
    # 枠がない (available = False)
    status_unavailable = {"available": False, "remaining": 0}
    # 2時間以下
    recs_2h = _get_wait_recommendations("premium", status_unavailable, {"remaining_hours": 1, "remaining_display": "1時間"})
    assert len(recs_2h) == 1
    assert recs_2h[0]["type"] == "wait"
    # 6時間以下
    recs_6h = _get_wait_recommendations("premium", status_unavailable, {"remaining_hours": 4, "remaining_display": "4時間"})
    assert len(recs_6h) == 1
    assert recs_6h[0]["type"] == "consider"
    # 6時間超
    recs_long = _get_wait_recommendations("premium", status_unavailable, {"remaining_hours": 8, "remaining_display": "8時間"})
    assert len(recs_long) == 1
    assert recs_long[0]["type"] == "fallback"

    # 枠がある (available = True)
    # 残り10未満
    status_low = {"available": True, "remaining": 5}
    recs_low = _get_wait_recommendations("premium", status_low, {})
    assert len(recs_low) == 1
    assert recs_low[0]["type"] == "caution"
    # 残り10以上
    status_high = {"available": True, "remaining": 15}
    recs_high = _get_wait_recommendations("premium", status_high, {})
    assert len(recs_high) == 0

# ------------------------------------------------------------
# 2. エンドポイントのテスト
# ------------------------------------------------------------

def test_dashboard_success():
    """/dashboard エンドポイントの正常系テスト"""
    mock_summary = {
        "date": "2026-05-30",
        "models": {
            "gemini-2.5-flash": {
                "used": 10,
                "limit": 100,
                "remaining": 90,
                "usage_ratio": 0.1,
                "alert_level": "normal"
            },
            "gemini-2.5-pro": {
                "used": 45,
                "limit": 50,
                "remaining": 5,
                "usage_ratio": 0.9,
                "alert_level": "warning"
            }
        }
    }
    with patch("usage_tracker.usage_tracker.get_daily_summary", return_value=mock_summary):
        response = client.get("/api/usage/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-05-30"
        assert len(data["models"]) == 2
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["model"] == "gemini-2.5-pro"
        assert "節約モード" in data["recommendations"][0]

def test_dashboard_all_normal():
    """すべてのモデルが正常な場合に「すべてのモデルが正常範囲内です」が出ること"""
    mock_summary = {
        "date": "2026-05-30",
        "models": {
            "gemini-2.5-flash": {
                "used": 10,
                "limit": 100,
                "remaining": 90,
                "usage_ratio": 0.1,
                "alert_level": "normal"
            }
        }
    }
    with patch("usage_tracker.usage_tracker.get_daily_summary", return_value=mock_summary):
        response = client.get("/api/usage/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "すべてのモデルが正常範囲内" in data["recommendations"][0]

def test_dashboard_critical_alert():
    """ダッシュボードでcriticalアラート時の処理"""
    mock_summary = {
        "date": "2026-05-30",
        "models": {
            "gemini-2.5-pro": {
                "used": 50,
                "limit": 50,
                "remaining": 0,
                "usage_ratio": 1.0,
                "alert_level": "critical"
            }
        }
    }
    with patch("usage_tracker.usage_tracker.get_daily_summary", return_value=mock_summary):
        response = client.get("/api/usage/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "翌日まで待つ" in data["recommendations"][0]

def test_dashboard_exception():
    """ダッシュボード取得で一般例外が発生した際のフォールバック処理"""
    with patch("usage_tracker.usage_tracker.get_daily_summary", side_effect=Exception("Database down")):
        response = client.get("/api/usage/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == ""
        assert len(data["alerts"]) == 1
        assert "使用量データの取得に失敗" in data["alerts"][0]["message"]

def test_dashboard_http_exception():
    """ダッシュボード取得でHTTPExceptionが発生した際はそのまま返ること"""
    with patch("usage_tracker.usage_tracker.get_daily_summary", side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.get("/api/usage/dashboard")
        assert response.status_code == 403

def test_get_remaining_requests_api():
    """GET /remaining/{model_name} のテスト"""
    with patch("usage_tracker.usage_tracker.get_remaining_requests", return_value=85), \
         patch("usage_tracker.usage_tracker.can_make_request", return_value=True), \
         patch("usage_tracker.usage_tracker.get_usage_ratio", return_value=0.15):
        response = client.get("/api/usage/remaining/gemini-2.5-flash")
        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "gemini-2.5-flash"
        assert data["remaining"] == 85
        assert data["can_use"] is True
        assert data["usage_percent"] == 15.0
        assert data["warning"] is False

def test_get_retry_budget_success():
    """GET /retry-budget の正常系テスト"""
    mock_summary = {
        "models": {
            "quality_model": {
                "remaining": 22,
                "usage_ratio": 0.4
            },
            "proof_model": {
                "remaining": 60,
                "usage_ratio": 0.2
            }
        }
    }
    with patch("usage_tracker.usage_tracker.get_daily_summary", return_value=mock_summary), \
         patch("routers.usage_router.get_model", side_effect=lambda task: "quality_model" if task == "quality_gate" else "proof_model"):
        response = client.get("/api/usage/retry-budget")
        assert response.status_code == 200
        data = response.json()
        assert data["premium"]["remaining_requests"] == 22
        assert data["premium"]["estimated_retries"] == 11
        assert data["premium"]["warning"] is False
        assert data["standard"]["remaining_requests"] == 60
        assert data["standard"]["estimated_retries"] == 20
        assert data["standard"]["warning"] is False
        assert "十分な余裕" in data["advice"]

def test_get_retry_budget_exception():
    """GET /retry-budget で一般例外が発生した際の処理"""
    with patch("usage_tracker.usage_tracker.get_daily_summary", side_effect=Exception("API limit exceeded")):
        response = client.get("/api/usage/retry-budget")
        assert response.status_code == 200
        data = response.json()
        assert data["premium"]["estimated_retries"] == 0
        assert data["premium"]["warning"] is True
        assert "予算データの取得に失敗" in data["advice"]

def test_get_retry_budget_http_exception():
    """GET /retry-budget でHTTPExceptionが発生した際はそのまま返ること"""
    with patch("usage_tracker.usage_tracker.get_daily_summary", side_effect=HTTPException(status_code=401, detail="Unauthorized")):
        response = client.get("/api/usage/retry-budget")
        assert response.status_code == 401

def test_get_quality_warning_critical():
    """GET /quality-warning で高品質モデルが使えない場合"""
    with patch("usage_tracker.usage_tracker.can_make_request", return_value=False), \
         patch("usage_tracker.usage_tracker.get_usage_ratio", return_value=1.0), \
         patch("routers.usage_router.get_model", return_value="gemini-2.5-pro"):
        response = client.get("/api/usage/quality-warning")
        assert response.status_code == 200
        data = response.json()
        assert data["warning"] is True
        assert data["level"] == "critical"

def test_get_quality_warning_warning():
    """GET /quality-warning で高品質モデルの使用率が 80% を超えている場合"""
    with patch("usage_tracker.usage_tracker.can_make_request", return_value=True), \
         patch("usage_tracker.usage_tracker.get_usage_ratio", return_value=0.85), \
         patch("routers.usage_router.get_model", return_value="gemini-2.5-pro"):
        response = client.get("/api/usage/quality-warning")
        assert response.status_code == 200
        data = response.json()
        assert data["warning"] is True
        assert data["level"] == "warning"
        assert "15%" in data["message"]

def test_get_quality_warning_normal():
    """GET /quality-warning で正常な場合"""
    with patch("usage_tracker.usage_tracker.can_make_request", return_value=True), \
         patch("usage_tracker.usage_tracker.get_usage_ratio", return_value=0.3), \
         patch("routers.usage_router.get_model", return_value="gemini-2.5-pro"):
        response = client.get("/api/usage/quality-warning")
        assert response.status_code == 200
        data = response.json()
        assert data["warning"] is False
        assert data["level"] == "normal"

def test_get_model_status():
    """GET /model-status のテスト"""
    mock_status = {"tiers": {"premium": {"status": "normal"}}}
    mock_qm = MagicMock()
    mock_qm.get_all_models_status.return_value = mock_status
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/model-status")
        assert response.status_code == 200
        assert response.json() == mock_status

def test_get_switch_history():
    """GET /switch-history のテスト"""
    mock_history = [{"original_model": "pro", "fallback_model": "flash"}]
    mock_qm = MagicMock()
    mock_qm.get_switch_history.return_value = mock_history
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/switch-history?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["history"] == mock_history

def test_get_available_model_api():
    """POST /get-model のテスト"""
    # **期待値を直書きしない**（R1.5-C6）。段の実体は model_config.json が正典
    from model_policy import resolve
    既定 = resolve("quality_gate").model
    mock_result = {"model": 既定, "available": True}
    mock_qm = MagicMock()
    mock_qm.get_available_model.return_value = mock_result
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/get-model?preferred_model=gemini-2.5-pro&task=test")
        assert response.status_code == 200
        assert response.json() == mock_result

def test_get_current_model_for_task_success():
    """GET /current-model/{task} の正常系"""
    mock_result = {"model": "gemini-2.5-flash", "available": True}
    mock_qm = MagicMock()
    mock_qm.get_available_model.return_value = mock_result
    with patch("model_registry.get_model", return_value="gemini-2.5-pro"), \
         patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/current-model/quality_gate")
        assert response.status_code == 200
        data = response.json()
        assert data["task"] == "quality_gate"
        assert data["preferred_model"] == "gemini-2.5-pro"
        assert data["model"] == "gemini-2.5-flash"

def test_get_current_model_for_task_http_exception():
    """GET /current-model/{task} で HTTPException が発生した場合"""
    with patch("model_registry.get_model", side_effect=HTTPException(status_code=404, detail="Not Found")):
        response = client.get("/api/usage/current-model/non-existent-task")
        assert response.status_code == 404

def test_get_current_model_for_task_exception():
    """GET /current-model/{task} で一般例外が発生した場合、デフォルトモデルになること"""
    # **期待値を直書きしない**（R1.5-C6）。正典は model_config.json。
    # ここは model_registry.get_model を落としているので、ルータは工程別の
    # モデルではなく既定モデルに落ちる
    from model_policy import default_model
    既定 = default_model()
    mock_result = {"model": 既定, "available": True}
    mock_qm = MagicMock()
    mock_qm.get_available_model.return_value = mock_result
    with patch("model_registry.get_model", side_effect=Exception("Fail to read model")), \
         patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/current-model/quality_gate")
        assert response.status_code == 200
        data = response.json()
        assert data["preferred_model"] == 既定
        assert not data["preferred_model"].startswith("gemini-2.5")

def test_get_two_tier_status_api():
    """GET /two-tier-status のテスト"""
    mock_status = {"status": "ok"}
    mock_qm = MagicMock()
    mock_qm.get_two_tier_status.return_value = mock_status
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/two-tier-status")
        assert response.status_code == 200
        assert response.json() == mock_status

def test_get_wait_options_api():
    """GET /wait-options のテスト"""
    mock_wait = {"model": "gemini-2.5-pro", "available": False}
    mock_reset = {"remaining_hours": 3, "remaining_display": "3時間"}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    mock_qm.get_time_until_reset.return_value = mock_reset
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.get("/api/usage/wait-options?tier=premium")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "premium"
        assert data["current_status"] == mock_wait
        assert data["reset_info"] == mock_reset
        assert len(data["recommendations"]) == 1

# ------------------------------------------------------------
# 3. select-option のテスト
# ------------------------------------------------------------

def test_select_option_wait():
    """POST /select-option (option=wait)"""
    mock_wait = {"model": "gemini-2.5-pro", "available": False}
    mock_reset = {"remaining_display": "2時間", "reset_time_jst": "15:00"}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    mock_qm.get_time_until_reset.return_value = mock_reset
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=wait")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "wait"
        assert "2時間" in data["message"]

def test_select_option_force_available():
    """POST /select-option (option=force) 枠あり"""
    mock_wait = {"available": True}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    mock_qm.MODEL_TIERS = {"premium": {"model": "gemini-2.5-pro"}}
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=force")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "force"
        assert data["model"] == "gemini-2.5-pro"

def test_select_option_force_unavailable():
    """POST /select-option (option=force) 枠なしエラー"""
    mock_wait = {"available": False, "options": {"force": {"available": False}}}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=force")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "error"
        assert "枠がありません" in data["message"]

def test_select_option_fallback():
    """POST /select-option (option=fallback)"""
    mock_wait = {}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    mock_qm.MODEL_TIERS = {"premium": {"model": "gemini-2.5-pro"}}
    mock_qm.FALLBACK_CHAIN = {"gemini-2.5-pro": "gemini-2.5-flash"}
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=fallback")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "fallback"
        assert data["model"] == "gemini-2.5-flash"

def test_select_option_auto():
    """POST /select-option (option=auto またはデフォルト)"""
    mock_wait = {"model": "gemini-2.5-flash", "tier": "standard"}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=auto")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "auto"
        assert data["model"] == "gemini-2.5-flash"

# ------------------------------------------------------------
# 4. モデルガバナンスのエンドポイントテスト
# ------------------------------------------------------------

def test_governance_success():
    """GET /governance の正常系テスト"""
    mock_stats = {
        "fallback_chain": {"a": "b"},
        "deprecation_map": {"x": "y"},
        "deprecation_corrections": 5,
        "fallback_activations": 2,
        "total_api_errors": 1,
        "recent_events": ["event1"]
    }
    mock_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-pro", "label": "Pro", "description": "Desc"}
            }
        },
        "grade_policy": {"policy": "strict"}
    }
    mock_summary = {
        "date": "2026-05-30",
        "models": {"gemini-pro": {}}
    }
    with patch("model_governance.model_governance.get_stats", return_value=mock_stats), \
         patch("builtins.open", mock_open(read_data=json.dumps(mock_config))), \
         patch("usage_tracker.tracker.usage_tracker.get_daily_summary", return_value=mock_summary):
        response = client.get("/api/usage/governance")
        assert response.status_code == 200
        data = response.json()
        assert data["grade_policy"]["policy"] == "strict"
        assert data["tiers"]["premium"]["model"] == "gemini-pro"
        assert data["usage"]["date"] == "2026-05-30"
        assert data["counters"]["deprecation_corrections"] == 5

def test_governance_exceptions():
    """GET /governance 各部分の例外発生時の耐性テスト"""
    with patch.dict("sys.modules", {"model_governance": None, "usage_tracker.tracker": None}), \
         patch("builtins.open", side_effect=Exception("Config Open Error")):
        response = client.get("/api/usage/governance")
        assert response.status_code == 200
        data = response.json()
        assert data["fallback_chain"] == {}
        assert data["tiers"] == {}
        assert data["usage"] == {}
        assert data["counters"]["deprecation_corrections"] == 0

def test_governance_http_exceptions():
    """GET /governance で HTTPException が発生した場合は透過的に raise されること"""
    with patch("builtins.open", side_effect=HTTPException(status_code=400, detail="HTTP Bad Config")):
        response = client.get("/api/usage/governance")
        assert response.status_code == 400

    # usage_tracker で HTTPException
    with patch("model_governance.model_governance.get_stats", return_value={}), \
         patch("builtins.open", mock_open(read_data="{}")), \
         patch("usage_tracker.tracker.usage_tracker.get_daily_summary", side_effect=HTTPException(status_code=401, detail="Unauthorized")):
        response = client.get("/api/usage/governance")
        assert response.status_code == 401

def test_governance_reload_success():
    """POST /governance/reload の正常系テスト"""
    mock_stats = {"fallback_chain": {"a": "b"}}
    with patch("model_governance.model_governance.reload") as mock_gov_reload, \
         patch("model_governance.model_governance.get_stats", return_value=mock_stats), \
         patch("model_registry.ModelRegistry._load_config") as mock_reg_reload:
        response = client.post("/api/usage/governance/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
        assert data["governance"]["status"] == "reloaded"
        assert data["governance"]["fallback_chain"] == {"a": "b"}
        assert data["registry"]["status"] == "reloaded"

def test_governance_reload_exceptions():
    """POST /governance/reload で例外が発生した際のエラー報告"""
    with patch("model_governance.model_governance.reload", side_effect=Exception("Gov Fail")), \
         patch("model_registry.ModelRegistry._load_config", side_effect=Exception("Reg Fail")):
        response = client.post("/api/usage/governance/reload")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
        assert data["governance"]["status"] == "error"
        assert "Gov Fail" in data["governance"]["message"]
        assert data["registry"]["status"] == "error"
        assert "Reg Fail" in data["registry"]["message"]

def test_governance_reload_http_exceptions():
    """POST /governance/reload で HTTPException が発生した場合は透過されること"""
    with patch("model_governance.model_governance.reload", side_effect=HTTPException(status_code=403, detail="Forbidden")):
        response = client.post("/api/usage/governance/reload")
        assert response.status_code == 403

    with patch("model_governance.model_governance.reload"), \
         patch("model_registry.ModelRegistry._load_config", side_effect=HTTPException(status_code=400, detail="Bad config")):
        response = client.post("/api/usage/governance/reload")
        assert response.status_code == 400

# ------------------------------------------------------------
# 5. サムネイル生成 API のテスト (/api/thumbnail/generate)
# ------------------------------------------------------------

def test_thumbnail_resolution_validation():
    """サムネイル生成: 解像度のバリデーション"""
    response = client.post(
        "/api/thumbnail/generate",
        json={"task_id": "t1", "width": 1000, "height": 720}
    )
    assert response.status_code == 400
    assert "Resolution must be at least 1280x720" in response.json()["detail"]

def test_thumbnail_aspect_ratio_validation():
    """サムネイル生成: アスペクト比が 16:9 ではない場合"""
    response = client.post(
        "/api/thumbnail/generate",
        json={"task_id": "t2", "width": 1280, "height": 800}
    )
    assert response.status_code == 400
    assert "Aspect ratio must be 16:9" in response.json()["detail"]

@pytest.mark.asyncio
async def test_thumbnail_success():
    """サムネイル生成: 正常系のテスト"""
    mock_overlay = MagicMock()
    mock_agent = MagicMock()
    
    # 複数回呼び出しを安全にハンドリングする side_effect 関数
    call_count = 0
    def get_status_side_effect(task_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "READY"
        elif call_count == 2:
            return "RUNNING"
        else:
            return "COMPLETED"
            
    mock_agent.get_task_status = AsyncMock(side_effect=get_status_side_effect)
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    # sqlite3 接続のモック
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (json.dumps({"image_path": "thumbnail.png"}),)
    mock_conn.execute.return_value = mock_cursor
    
    with patch("combined_overlay.CombinedOverlay", return_value=mock_overlay), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        response = client.post(
            "/api/thumbnail/generate",
            json={
                "task_id": "task_ok",
                "text": "Hello",
                "width": 1920,
                "height": 1080,
                "db_path": "mock.db",
                "output_dir": "mock_dir"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task_id"] == "task_ok"
        assert data["status"] == "COMPLETED"
        assert data["result"]["image_path"] == "thumbnail.png"

@pytest.mark.asyncio
async def test_thumbnail_failed():
    """サムネイル生成: タスク失敗時の挙動"""
    mock_overlay = MagicMock()
    mock_agent = MagicMock()
    
    # 複数回呼び出しを安全にハンドリングする side_effect 関数
    call_count = 0
    def get_status_side_effect(task_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "RUNNING"
        else:
            return "FAILED"
            
    mock_agent.get_task_status = AsyncMock(side_effect=get_status_side_effect)
    mock_agent.register_task = AsyncMock()
    mock_agent.start = AsyncMock()
    mock_agent.stop = AsyncMock()
    
    # sqlite3
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("Overlay generation timeout",)
    mock_conn.execute.return_value = mock_cursor
    
    with patch("combined_overlay.CombinedOverlay", return_value=mock_overlay), \
         patch("agents.stage_bound_agent.StageBoundAgent", return_value=mock_agent), \
         patch("sqlite3.connect", return_value=mock_conn), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        response = client.post(
            "/api/thumbnail/generate",
            json={
                "task_id": "task_fail",
                "width": 1280,
                "height": 720
            }
        )
        assert response.status_code == 500
        assert "Thumbnail task failed: Overlay generation timeout" in response.json()["detail"]

# ------------------------------------------------------------
# 6. インポートフォールバックのテスト (16-18行目)
# ------------------------------------------------------------

def test_model_registry_import_error_fallback():
    """model_registry が無い場合の import fallback と get_model 関数の動作検証"""
    with patch.dict("sys.modules", {"model_registry": None}):
        usage_router_module = sys.modules.get("routers.usage_router")
        if usage_router_module:
            importlib.reload(usage_router_module)
            fallback_get_model = getattr(usage_router_module, "get_model")
            # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
            # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
            from model_policy import resolve
            assert fallback_get_model("any_task") == resolve("any_task").model
            assert not fallback_get_model("any_task").startswith("gemini-2.5")
        
    # 元に戻す
    usage_router_module = sys.modules.get("routers.usage_router")
    if usage_router_module:
        importlib.reload(usage_router_module)


def test_legacy_thumbnail_request_docstring():
    """LegacyThumbnailRequest クラスの docstring の存在と内容をテスト"""
    from routers.usage_router import LegacyThumbnailRequest
    doc = LegacyThumbnailRequest.__doc__
    assert doc is not None
    assert "レガシーサムネイル生成リクエストのモデル" in doc
    assert "task_id" in doc
    assert "width" in doc
    assert "height" in doc


def test_fallback_get_model_docstring():
    """インポートエラーフォールバック時の get_model 関数の docstring の存在をテスト"""
    with patch.dict("sys.modules", {"model_registry": None}):
        usage_router_module = sys.modules.get("routers.usage_router")
        if usage_router_module:
            importlib.reload(usage_router_module)
            fallback_get_model = getattr(usage_router_module, "get_model")
            doc = fallback_get_model.__doc__
            assert doc is not None
            assert "モデル名を取得するフォールバック関数" in doc

    # 元に戻す
    usage_router_module = sys.modules.get("routers.usage_router")
    if usage_router_module:
        importlib.reload(usage_router_module)


def test_all_functions_have_detailed_docstring():
    """usage_router 内の主要な関数が Google スタイルの詳細な docstring を持っていることを検証"""
    import sys
    import inspect
    ur = sys.modules.get("routers.usage_router")
    assert ur is not None, "routers.usage_router module is not loaded"

    functions_to_test = [
        ur.get_model,
        ur._format_dashboard_models_and_alerts,
        ur._generate_dashboard_recommendations,
        ur.get_usage_dashboard,
        ur.get_remaining_requests,
        ur._format_tier_budget,
        ur.get_retry_budget,
        ur.get_quality_warning,
        ur._get_tier_label,
        ur._get_alert_message,
        ur._get_retry_advice,
        ur.get_all_models_status,
        ur.get_switch_history,
        ur.get_available_model,
        ur.get_current_model_for_task,
        ur.get_two_tier_status,
        ur.get_wait_options,
        ur.select_model_option,
        ur._get_wait_recommendations,
        ur.get_governance_status,
        ur.reload_governance_config,
        ur._validate_thumbnail_request,
        ur._setup_thumbnail_overlay_and_agent,
        ur._wait_for_thumbnail_task,
        ur._fetch_thumbnail_result,
        ur.generate_thumbnail_api,
    ]

    for func in functions_to_test:
        # 他モジュールからインポートされた関数はスキップする
        if inspect.getmodule(func) != ur:
            continue

        doc = func.__doc__
        assert doc is not None, f"Function {func.__name__} has no docstring"
        
        # Googleスタイルのセクションの存在確認
        sig = inspect.signature(func)
        
        # 引数があるか
        has_args = len([p for p in sig.parameters.values() if p.name not in ('self', 'cls')]) > 0
        if has_args:
            assert "Args:" in doc, f"Function {func.__name__} should have 'Args:' in docstring. Got: {doc}"
            
        # 戻り値があるか（戻り値の型が None 以外、または指定されている）
        has_return = sig.return_annotation is not inspect.Signature.empty
        if has_return:
            return_str = str(sig.return_annotation)
            if "None" not in return_str and "inspect.Signature.empty" not in return_str:
                assert "Returns:" in doc or "Yields:" in doc, f"Function {func.__name__} should have 'Returns:' in docstring. Got: {doc}"

        # Raises のチェック: 実装内で raise している場合は Raises: が含まれるべき
        # （コメントアウトされた raise は除外するため、単純な判定のほか、実コード行での raise 検出）
        source = inspect.getsource(func)
        # コメント行を除いた実コード行に raise が含まれるか
        has_raise = False
        for line in source.splitlines():
            line_strip = line.strip()
            if line_strip.startswith("raise ") or (" raise " in line_strip and not line_strip.startswith("#")):
                has_raise = True
                break
        if has_raise:
            assert "Raises:" in doc, f"Function {func.__name__} raises an exception and should have 'Raises:' in docstring. Got: {doc}"


def test_select_option_invalid_option():
    """POST /select-option (無効なoption指定時のフォールバック動作のテスト)"""
    mock_wait = {"model": "gemini-2.5-flash", "tier": "standard"}
    mock_qm = MagicMock()
    mock_qm.get_model_with_wait_option.return_value = mock_wait
    with patch("usage_tracker.quota_manager", mock_qm):
        response = client.post("/api/usage/select-option?tier=premium&option=invalid_value")
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "auto"
        assert data["model"] == "gemini-2.5-flash"


def test_governance_json_decode_error():
    """GET /governance (model_config.json の JSONデコードエラー発生時の耐性テスト)"""
    mock_stats = {
        "fallback_chain": {"a": "b"},
        "deprecation_map": {},
        "deprecation_corrections": 0,
        "fallback_activations": 0,
        "total_api_errors": 0,
        "recent_events": []
    }
    with patch("model_governance.model_governance.get_stats", return_value=mock_stats), \
         patch("builtins.open", mock_open(read_data="invalid json { data")), \
         patch("usage_tracker.tracker.usage_tracker.get_daily_summary", return_value={}):
        response = client.get("/api/usage/governance")
        assert response.status_code == 200
        data = response.json()
        assert data["grade_policy"] == {}
        assert data["tiers"] == {}
        assert data["usage"] == {"date": None, "models": {}}


def test_docstring_return_type_matches_signature():
    """usage_router 内の主要な関数の戻り値型シグネチャと docstring の Returns 記載が一致していることを検証"""
    import sys
    import inspect
    import re
    ur = sys.modules.get("routers.usage_router")
    assert ur is not None, "routers.usage_router module is not loaded"

    functions_to_test = [
        ur.get_model,
        ur._format_dashboard_models_and_alerts,
        ur._generate_dashboard_recommendations,
        ur.get_usage_dashboard,
        ur.get_remaining_requests,
        ur._format_tier_budget,
        ur.get_retry_budget,
        ur.get_quality_warning,
        ur._get_tier_label,
        ur._get_alert_message,
        ur._get_retry_advice,
        ur.get_all_models_status,
        ur.get_switch_history,
        ur.get_available_model,
        ur.get_current_model_for_task,
        ur.get_two_tier_status,
        ur.get_wait_options,
        ur.select_model_option,
        ur._get_wait_recommendations,
        ur.get_governance_status,
        ur.reload_governance_config,
        ur._validate_thumbnail_request,
        ur._setup_thumbnail_overlay_and_agent,
        ur._wait_for_thumbnail_task,
        ur._fetch_thumbnail_result,
        ur.generate_thumbnail_api,
    ]

    for func in functions_to_test:
        if inspect.getmodule(func) != ur:
            continue

        sig = inspect.signature(func)
        doc = func.__doc__
        assert doc is not None, f"Function {func.__name__} has no docstring"

        # 戻り値の型アノテーションを取得
        return_anno = sig.return_annotation
        if return_anno is inspect.Signature.empty:
            continue

        # 戻り値アノテーションの文字列表記
        return_str = str(return_anno)
        return_str = re.sub(r"<class '([^']+)'>", r"\1", return_str)

        return_str = return_str.replace("typing.", "").replace("NoneType", "None").strip()
        return_str = return_str.replace("'", "").replace('"', '')

        # docstring から Returns/Yields の型表記を抽出
        match = re.search(r'(?:Returns|Yields):\s*\n?\s*([a-zA-Z0-9_\[\],"\s\'\-\>:]+?):', doc)
        if match:
            doc_type = match.group(1).strip()
            doc_type_clean = doc_type.replace("typing.", "").replace("'", "").replace('"', '')
            normalized_sig = return_str.lower().replace(" ", "")
            normalized_doc = doc_type_clean.lower().replace(" ", "")

            # 例外的な前方参照と実名の一致
            assert normalized_sig == normalized_doc, f"Function {func.__name__} has return type mismatch: signature={return_str}, docstring={doc_type}"

