import sys
import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from unittest.mock import MagicMock, patch

# パスの解決
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
backend_dir = os.path.join(project_root, "backend")

# 既存のパス登録を削除して優先順位を制御する
if backend_dir in sys.path:
    sys.path.remove(backend_dir)
if project_root in sys.path:
    sys.path.remove(project_root)

sys.path.insert(0, project_root)
sys.path.append(backend_dir)

import importlib.util
from pathlib import Path
_routers_dir = Path(project_root) / "routers"
_spec = importlib.util.spec_from_file_location("backend.routers.themes_router", str(_routers_dir / "themes_router.py"))
themes_router = importlib.util.module_from_spec(_spec)
sys.modules["backend.routers.themes_router"] = themes_router
_spec.loader.exec_module(themes_router)

# テスト用のFastAPIアプリ
app = FastAPI()
app.include_router(themes_router.router)
client = TestClient(app)


# ============================================================
# テスト用フィクスチャ (evolution_log.json のクリーンアップと退避)
# ============================================================

@pytest.fixture(autouse=True)
def setup_evolution_log():
    # themes_router と同じ経路で解決する。モジュールの位置から組み立てると
    # 本番の backend/branding/ を指し、autouse なのでこのファイルの全テストが
    # 本番の evolution_log.json を退避・削除・復元していた（2026-08-01 実測で
    # 260 件）。復元するとはいえ、途中で落ちれば本番ファイルが消える。
    log_path = themes_router._writable_path("backend/branding/evolution_log.json")
    branding_dir = log_path.parent
    
    # branding ディレクトリ作成
    branding_dir.mkdir(parents=True, exist_ok=True)
    
    # 既存ファイルの退避
    backup_path = branding_dir / "evolution_log.json.backup"
    has_backup = False
    if log_path.exists():
        try:
            log_path.rename(backup_path)
            has_backup = True
        except Exception:
            backup_path.write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
            has_backup = True
            log_path.unlink()
            
    yield log_path
    
    # テストファイルのクリーンアップ
    if log_path.exists():
        try:
            log_path.unlink()
        except Exception:
            pass
            
    # バックアップの復元
    if has_backup and backup_path.exists():
        try:
            if log_path.exists():
                log_path.unlink()
            backup_path.rename(log_path)
        except Exception:
            pass


# ============================================================
# GET /themes/health
# ============================================================

def test_health_check():
    response = client.get("/themes/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "themes"
    assert data["templates_count"] == len(themes_router.PRODUCTION_TEMPLATES)
    assert data["themes_count"] == len(themes_router.MOOD_THEMES)


# ============================================================
# GET /themes/templates
# ============================================================

def test_list_templates():
    response = client.get("/themes/templates")
    assert response.status_code == 200
    data = response.json()
    assert "templates" in data
    assert data["count"] == len(themes_router.PRODUCTION_TEMPLATES)
    for tmpl in data["templates"]:
        assert "recommended_themes" in tmpl


# ============================================================
# GET /themes/templates/{template_id}
# ============================================================

def test_get_template_success():
    template_id = "nhk_documentary"
    response = client.get(f"/themes/templates/{template_id}")
    assert response.status_code == 200
    data = response.json()
    assert "template" in data
    assert data["template"]["id"] == template_id
    assert "recommended_themes" in data
    assert "available_themes" in data

def test_get_template_not_found():
    template_id = "non_existent_template"
    response = client.get(f"/themes/templates/{template_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ============================================================
# GET /themes
# ============================================================

def test_list_themes():
    response = client.get("/themes")
    assert response.status_code == 200
    data = response.json()
    assert "themes" in data
    assert data["count"] == len(themes_router.MOOD_THEMES)


# ============================================================
# GET /themes/{theme_id}
# ============================================================

def test_get_theme_success():
    theme_id = "warm"
    response = client.get(f"/themes/{theme_id}")
    assert response.status_code == 200
    data = response.json()
    assert "theme" in data
    assert data["theme"]["id"] == theme_id

def test_get_theme_not_found():
    theme_id = "non_existent_theme"
    response = client.get(f"/themes/{theme_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ============================================================
# POST /themes/apply
# ============================================================

@patch("design_system.design_token_manager.design_token_manager")
@patch("template_config.template_config")
@patch("backend.routers.themes_router._record_template_selection")
def test_apply_success(mock_record, mock_template_config, mock_token_manager):
    mock_token_manager.update_tokens.return_value = {"updated": True}
    
    payload = {
        "template_id": "nhk_documentary",
        "theme_id": "cool",
        "reason": "テスト適用"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "applied"
    assert data["template"]["id"] == "nhk_documentary"
    assert data["theme"]["id"] == "cool"
    assert data["pipeline_connected"] is True
    
    mock_template_config.set_active_template.assert_called_once()
    mock_token_manager.update_tokens.assert_called_once()
    mock_record.assert_called_once_with("nhk_documentary", "cool")

def test_apply_invalid_template():
    payload = {
        "template_id": "non_existent_template",
        "theme_id": "cool"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()

def test_apply_invalid_theme():
    payload = {
        "template_id": "nhk_documentary",
        "theme_id": "non_existent_theme"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()

@patch("design_system.design_token_manager.design_token_manager")
@patch("template_config.template_config")
@patch("backend.routers.themes_router._record_template_selection")
def test_apply_general_exception(mock_record, mock_template_config, mock_token_manager):
    mock_token_manager.update_tokens.side_effect = ValueError("Token update failed")
    
    payload = {
        "template_id": "nhk_documentary",
        "theme_id": "cool"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 500
    assert "Token update failed" in response.json()["detail"]

@patch("design_system.design_token_manager.design_token_manager")
@patch("template_config.template_config")
@patch("backend.routers.themes_router._record_template_selection")
def test_apply_http_exception(mock_record, mock_template_config, mock_token_manager):
    mock_token_manager.update_tokens.side_effect = HTTPException(status_code=400, detail="HTTP error")
    
    payload = {
        "template_id": "nhk_documentary",
        "theme_id": "cool"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "HTTP error"

def test_apply_template_config_import_error():
    with patch.dict(sys.modules, {"template_config": None}):
        with patch("design_system.design_token_manager.design_token_manager") as mock_token_manager:
            mock_token_manager.update_tokens.return_value = {"updated": True}
            payload = {
                "template_id": "nhk_documentary",
                "theme_id": "cool"
            }
            response = client.post("/themes/apply", json=payload)
            assert response.status_code == 200
            assert response.json()["status"] == "applied"

def test_apply_design_token_manager_import_error():
    with patch.dict(sys.modules, {"design_system.design_token_manager": None}):
        payload = {
            "template_id": "nhk_documentary",
            "theme_id": "cool"
        }
        response = client.post("/themes/apply", json=payload)
        assert response.status_code == 500
        assert "design_token_manager not available" in response.json()["detail"]


# ============================================================
# GET /themes/current/active
# ============================================================

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_success_matched(mock_token_manager):
    mock_token_manager.get_change_history.return_value = [{
        "timestamp": "2026-05-21T12:00:00",
        "mood": "cool",
        "reason": "テンプレート '📺 NHKドキュメンタリー風' + テーマ '🧊 クール' を適用"
    }]
    
    response = client.get("/themes/current/active")
    assert response.status_code == 200
    data = response.json()
    assert data["template"]["id"] == "nhk_documentary"
    assert data["theme"]["id"] == "cool"
    assert data["applied_at"] == "2026-05-21T12:00:00"

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_success_unmatched(mock_token_manager):
    mock_token_manager.get_change_history.return_value = [{
        "timestamp": "2026-05-21T12:00:00",
        "mood": "non_existent_mood",
        "reason": "不明なアクション"
    }]
    
    response = client.get("/themes/current/active")
    assert response.status_code == 200
    data = response.json()
    assert data["template"] is None
    assert data["theme"] is None

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_empty(mock_token_manager):
    mock_token_manager.get_change_history.return_value = []
    
    response = client.get("/themes/current/active")
    assert response.status_code == 200
    data = response.json()
    assert data["template"] is None
    assert data["theme"] is None
    assert data["label"] == "未設定"

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_http_exception(mock_token_manager):
    mock_token_manager.get_change_history.side_effect = HTTPException(status_code=403, detail="Forbidden")
    
    response = client.get("/themes/current/active")
    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_general_exception(mock_token_manager):
    mock_token_manager.get_change_history.side_effect = ValueError("Database error")
    
    response = client.get("/themes/current/active")
    assert response.status_code == 500
    assert "Database error" in response.json()["detail"]


# ============================================================
# GET /themes/stats (Test Client ではなく直接呼び出す)
# ============================================================

@pytest.mark.asyncio
async def test_get_template_stats_success(setup_evolution_log):
    log_path = setup_evolution_log
    dummy_log = {
        "template_selections": [
            {"template_id": "nhk_documentary", "theme_id": "cool", "satisfaction": 4},
            {"template_id": "nhk_documentary", "theme_id": "warm", "satisfaction": 5},
            {"template_id": "mrbeast_entertainment", "theme_id": "energetic", "satisfaction": 2}
        ]
    }
    log_path.write_text(json.dumps(dummy_log, ensure_ascii=False), encoding="utf-8")
    
    data = await themes_router.get_template_stats()
    assert data["total_selections"] == 3
    assert data["by_template"]["nhk_documentary"] == 2
    assert data["by_template"]["mrbeast_entertainment"] == 1
    assert data["by_theme"]["cool"] == 1
    assert data["avg_satisfaction"]["nhk_documentary"] == 4.5
    assert data["avg_satisfaction"]["mrbeast_entertainment"] == 2.0

@pytest.mark.asyncio
async def test_get_template_stats_not_exist(setup_evolution_log):
    log_path = setup_evolution_log
    if log_path.exists():
        log_path.unlink()
        
    data = await themes_router.get_template_stats()
    assert data["stats"] == {}
    assert data["total_selections"] == 0

@pytest.mark.asyncio
async def test_get_template_stats_http_exception(setup_evolution_log):
    setup_evolution_log.write_text("{}", encoding="utf-8")
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore"), patch("agents.memory.technical_debt.TechnicalDebtStore"):
        with patch("json.loads", side_effect=HTTPException(status_code=400, detail="Mocked Bad Request")):
            with pytest.raises(Exception) as excinfo:
                await themes_router.get_template_stats()
            assert excinfo.value.__class__.__name__ == "HTTPException"
            assert excinfo.value.status_code == 400
            assert excinfo.value.detail == "Mocked Bad Request"

@pytest.mark.asyncio
async def test_get_template_stats_general_exception(setup_evolution_log):
    setup_evolution_log.write_text("{}", encoding="utf-8")
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore"), patch("agents.memory.technical_debt.TechnicalDebtStore"):
        with patch("json.loads", side_effect=ValueError("JSON decode error")):
            with pytest.raises(Exception) as excinfo:
                await themes_router.get_template_stats()
            assert excinfo.value.__class__.__name__ == "HTTPException"
            assert excinfo.value.status_code == 500
            assert "JSON decode error" in excinfo.value.detail


# ============================================================
# POST /themes/recommend
# ============================================================

@patch("template_recommender.template_recommender")
def test_recommend_success(mock_recommender):
    mock_recommender.recommend.return_value = ("nhk_documentary", {
        "score": 0.95,
        "reasons": ["ドキュメンタリージャンル判定"],
        "profile": {"genre": "documentary"}
    })
    mock_recommender.recommend_with_alternatives.return_value = [
        {"template_id": "asmr_relaxation", "score": 0.6}
    ]
    
    payload = {
        "segments": [{"text": "こんにちは", "start": 0, "end": 2}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["recommended"]["template_id"] == "nhk_documentary"
    assert data["recommended"]["score"] == 0.95
    assert len(data["alternatives"]) == 1

def test_recommend_import_error():
    with patch.dict(sys.modules, {"template_recommender": None}):
        payload = {
            "segments": [],
            "total_duration_seconds": 0.0
        }
        response = client.post("/themes/recommend", json=payload)
        assert response.status_code == 500
        assert "template_recommender not available" in response.json()["detail"]

@patch("template_recommender.template_recommender")
def test_recommend_http_exception(mock_recommender):
    mock_recommender.recommend.side_effect = HTTPException(status_code=400, detail="Recommendation error")
    
    payload = {
        "segments": [],
        "total_duration_seconds": 0.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Recommendation error"

@patch("template_recommender.template_recommender")
def test_recommend_general_exception(mock_recommender):
    mock_recommender.recommend.side_effect = ValueError("AI processing failed")
    
    payload = {
        "segments": [],
        "total_duration_seconds": 0.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 500
    assert "AI processing failed" in response.json()["detail"]


# ============================================================
# POST /themes/override
# ============================================================

@patch("template_config.template_config")
def test_override_success(mock_template_config):
    mock_template_config.is_active = True
    mock_template_config.template_id = "nhk_documentary"
    
    payload = {"overrides": {"subtitle_rules": {"font_size_min_px": 48}}}
    response = client.post("/themes/override", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "overridden"
    assert data["template_id"] == "nhk_documentary"
    assert "subtitle_rules" in data["overrides_applied"]
    
    mock_template_config.set_overrides.assert_called_once_with({"subtitle_rules": {"font_size_min_px": 48}})

@patch("template_config.template_config")
def test_override_inactive(mock_template_config):
    mock_template_config.is_active = False
    
    payload = {"overrides": {}}
    response = client.post("/themes/override", json=payload)
    assert response.status_code == 400
    assert "テンプレートが未選択です" in response.json()["detail"]

def test_override_import_error():
    with patch.dict(sys.modules, {"template_config": None}):
        payload = {"overrides": {}}
        response = client.post("/themes/override", json=payload)
        assert response.status_code == 500
        assert "template_config not available" in response.json()["detail"]


# ============================================================
# _record_template_selection (helper function)
# ============================================================

def test_record_template_selection_new_file(setup_evolution_log):
    log_path = setup_evolution_log
    if log_path.exists():
        log_path.unlink()
        
    themes_router._record_template_selection("nhk_documentary", "warm")
    
    assert log_path.exists()
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert "template_selections" in written_data
    assert len(written_data["template_selections"]) == 1
    assert written_data["template_selections"][0]["template_id"] == "nhk_documentary"
    assert written_data["template_selections"][0]["theme_id"] == "warm"

def test_record_template_selection_existing_file(setup_evolution_log):
    log_path = setup_evolution_log
    initial_log = {
        "template_selections": [
            {"template_id": "mrbeast_entertainment", "theme_id": "cool", "timestamp": "2026-05-21T00:00:00", "satisfaction": 3}
        ]
    }
    log_path.write_text(json.dumps(initial_log), encoding="utf-8")
    
    themes_router._record_template_selection("nhk_documentary", "warm")
    
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(written_data["template_selections"]) == 2
    assert written_data["template_selections"][0]["template_id"] == "mrbeast_entertainment"
    assert written_data["template_selections"][1]["template_id"] == "nhk_documentary"

def test_record_template_selection_cap_limit(setup_evolution_log):
    log_path = setup_evolution_log
    initial_selections = [{"template_id": "t", "theme_id": "m", "timestamp": str(i), "satisfaction": 3} for i in range(105)]
    initial_log = {"template_selections": initial_selections}
    log_path.write_text(json.dumps(initial_log), encoding="utf-8")
    
    themes_router._record_template_selection("new_template", "new_theme")
    
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(written_data["template_selections"]) == 100
    assert written_data["template_selections"][-1]["template_id"] == "new_template"

def test_record_template_selection_exception_safe(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("{}", encoding="utf-8")
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore"), patch("agents.memory.technical_debt.TechnicalDebtStore"):
        with patch("json.loads", side_effect=ValueError("Mocked JSON decode error")):
            try:
                themes_router._record_template_selection("nhk_documentary", "warm")
            except Exception as e:
                pytest.fail(f"_record_template_selection raised an exception: {e}")


# ============================================================
# 新規ガード・堅牢化のテスト (Task 23 追加分)
# ============================================================

@pytest.mark.asyncio
async def test_get_template_stats_data_not_dict(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("[]", encoding="utf-8")
    data = await themes_router.get_template_stats()
    assert data == {"stats": {}, "total_selections": 0}

@pytest.mark.asyncio
async def test_get_template_stats_selections_not_list(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text('{"template_selections": {}}', encoding="utf-8")
    data = await themes_router.get_template_stats()
    assert data == {
        "total_selections": 0,
        "by_template": {},
        "by_theme": {},
        "avg_satisfaction": {},
        "recent": []
    }

@pytest.mark.asyncio
async def test_get_template_stats_invalid_elements(setup_evolution_log):
    log_path = setup_evolution_log
    dummy_log = {
        "template_selections": [
            "invalid_element",
            {"template_id": "", "theme_id": "warm"},
            {"template_id": 123, "theme_id": "warm"},
            {"template_id": "nhk_documentary", "theme_id": 123, "satisfaction": "invalid_sat"},
            {"template_id": "nhk_documentary", "theme_id": "warm", "satisfaction": 4}
        ]
    }
    log_path.write_text(json.dumps(dummy_log), encoding="utf-8")
    data = await themes_router.get_template_stats()
    assert data["total_selections"] == 2
    assert data["by_template"]["nhk_documentary"] == 2

@pytest.mark.asyncio
async def test_get_template_stats_read_text_error(setup_evolution_log):
    log_path = setup_evolution_log
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        data = await themes_router.get_template_stats()
        assert data == {"stats": {}, "total_selections": 0}

@pytest.mark.asyncio
async def test_get_template_stats_general_exception_on_exists(setup_evolution_log):
    # exists()が例外を投げるケース
    orig_exists = Path.exists
    def mock_exists(self):
        if "evolution_log.json" in str(self):
            raise RuntimeError("Exists failed")
        return orig_exists(self)
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore"), patch("agents.memory.technical_debt.TechnicalDebtStore"):
        with patch.object(Path, "exists", mock_exists):
            with pytest.raises(Exception) as excinfo:
                await themes_router.get_template_stats()
            assert excinfo.value.__class__.__name__ == "HTTPException"
            assert excinfo.value.status_code == 500
            assert "Exists failed" in excinfo.value.detail

def test_apply_invalid_theme_structure():
    with patch.dict(themes_router.MOOD_THEMES, {"warm": {"invalid": "structure"}}):
        payload = {"template_id": "nhk_documentary", "theme_id": "warm"}
        response = client.post("/themes/apply", json=payload)
        assert response.status_code == 200
        assert "error" in response.json()
        assert "Invalid theme structure" in response.json()["error"]

@patch("design_system.design_token_manager.design_token_manager")
def test_apply_template_config_throws_exception(mock_token_manager):
    mock_token_manager.update_tokens.return_value = {"updated": True}
    with patch("template_config.template_config.set_active_template", side_effect=RuntimeError("Config error")):
        payload = {"template_id": "nhk_documentary", "theme_id": "warm"}
        response = client.post("/themes/apply", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "applied"

@patch("design_system.design_token_manager.design_token_manager")
@patch("template_config.template_config")
def test_apply_record_selection_throws_exception(mock_template_config, mock_token_manager):
    mock_token_manager.update_tokens.return_value = {"updated": True}
    with patch("backend.routers.themes_router._record_template_selection", side_effect=RuntimeError("Record error")):
        payload = {"template_id": "nhk_documentary", "theme_id": "warm"}
        response = client.post("/themes/apply", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "applied"

def test_get_current_config_design_token_manager_import_error():
    with patch.dict(sys.modules, {"design_system.design_token_manager": None}):
        response = client.get("/themes/current/active")
        assert response.status_code == 500
        assert "design_token_manager not available" in response.json()["detail"]

@patch("design_system.design_token_manager.design_token_manager")
def test_get_current_config_reason_not_string(mock_token_manager):
    mock_token_manager.get_change_history.return_value = [{
        "timestamp": "2026-05-21T12:00:00",
        "mood": "cool",
        "reason": 123
    }]
    response = client.get("/themes/current/active")
    assert response.status_code == 200
    assert response.json()["template"] is None

def test_recommend_template_recommender_import_error():
    with patch.dict(sys.modules, {"template_recommender": None}):
        payload = {"segments": [], "total_duration_seconds": 10.0}
        response = client.post("/themes/recommend", json=payload)
        assert response.status_code == 500
        assert "template_recommender not available" in response.json()["detail"]

@patch("template_recommender.template_recommender")
def test_recommend_invalid_result_structure(mock_recommender):
    mock_recommender.recommend.return_value = "not_a_tuple"
    payload = {"segments": [], "total_duration_seconds": 10.0}
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 200
    assert "Invalid recommendation result" in response.json()["error"]

@patch("template_recommender.template_recommender")
def test_recommend_detail_not_dict(mock_recommender):
    mock_recommender.recommend.return_value = ("nhk_documentary", "not_a_dict")
    mock_recommender.recommend_with_alternatives.return_value = "not_a_list"
    payload = {"segments": [], "total_duration_seconds": 10.0}
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["recommended"]["template_id"] == "nhk_documentary"
    assert data["recommended"]["score"] == 0.0
    assert data["alternatives"] == []

def test_record_template_selection_corrupted_json(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("{corrupted_json", encoding="utf-8")
    themes_router._record_template_selection("nhk_documentary", "warm")
    assert log_path.exists()
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(written_data["template_selections"]) == 1

def test_record_template_selection_not_dict(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("[]", encoding="utf-8")
    themes_router._record_template_selection("nhk_documentary", "warm")
    assert log_path.exists()
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert isinstance(written_data, dict)
    assert len(written_data["template_selections"]) == 1

def test_record_template_selection_selections_not_list(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text('{"template_selections": {}}', encoding="utf-8")
    themes_router._record_template_selection("nhk_documentary", "warm")
    assert log_path.exists()
    written_data = json.loads(log_path.read_text(encoding="utf-8"))
    assert isinstance(written_data["template_selections"], list)
    assert len(written_data["template_selections"]) == 1



# ============================================================
# カバレッジ 100% 達成のための追加テスト
# ============================================================

@pytest.mark.asyncio
async def test_get_template_stats_empty_file(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("", encoding="utf-8")
    data = await themes_router.get_template_stats()
    assert data == {"stats": {}, "total_selections": 0}

@pytest.mark.asyncio
async def test_get_template_stats_json_decode_error(setup_evolution_log):
    log_path = setup_evolution_log
    log_path.write_text("{invalid_json", encoding="utf-8")
    data = await themes_router.get_template_stats()
    assert data == {"stats": {}, "total_selections": 0}

@pytest.mark.asyncio
async def test_get_template_stats_empty_satisfaction_sats(setup_evolution_log):
    log_path = setup_evolution_log
    dummy_log = {
        "template_selections": [
            {"template_id": "nhk_documentary", "theme_id": "cool", "satisfaction": "not_a_number"},
            {"template_id": "mrbeast_entertainment", "theme_id": "energetic"}
        ]
    }
    log_path.write_text(json.dumps(dummy_log), encoding="utf-8")
    
    data = await themes_router.get_template_stats()
    assert data["avg_satisfaction"]["nhk_documentary"] == 3.0
    assert data["avg_satisfaction"]["mrbeast_entertainment"] == 3.0


# ============================================================
# Phase 27 / thumbnail タスク #2 (T-batch_3becc6-thumbnail-001) 追加テスト
# ============================================================

def test_recommend_invalid_segments_not_list():
    payload = {
        "segments": "not_a_list",
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 422

def test_recommend_invalid_segment_element_not_dict():
    payload = {
        "segments": ["not_a_dict"],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 422

def test_recommend_invalid_segment_missing_keys():
    payload = {
        "segments": [{"start": 1.0}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert "must contain 'start' and 'end' keys" in response.json()["detail"]

def test_recommend_invalid_segment_non_numeric_keys():
    payload = {
        "segments": [{"start": "one", "end": 2.0}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert "must be numbers" in response.json()["detail"]

def test_recommend_invalid_segment_negative_keys():
    payload = {
        "segments": [{"start": -1.0, "end": 2.0}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert "must be non-negative" in response.json()["detail"]

def test_recommend_invalid_segment_start_greater_than_end():
    payload = {
        "segments": [{"start": 5.0, "end": 2.0}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert "cannot be greater than" in response.json()["detail"]

def test_recommend_invalid_total_duration_negative():
    payload = {
        "segments": [],
        "total_duration_seconds": -1.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 400
    assert "must be a non-negative number" in response.json()["detail"]

def test_override_invalid_overrides_not_dict():
    payload = {
        "overrides": "not_a_dict"
    }
    response = client.post("/themes/override", json=payload)
    assert response.status_code == 422

@patch("template_config.template_config")
def test_override_set_overrides_exception(mock_template_config):
    mock_template_config.is_active = True
    mock_template_config.template_id = "nhk_documentary"
    mock_template_config.set_overrides.side_effect = ValueError("Failed to set values")
    
    try:
        from backend.agents.memory.technical_debt import TechnicalDebtStore
    except ImportError:
        from agents.memory.technical_debt import TechnicalDebtStore
        
    store = TechnicalDebtStore()
    old_count = store.get_critical_open_count()
    
    with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=store), \
         patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=store):
        
        payload = {"overrides": {"subtitle_rules": {"font_size_min_px": 48}}}
        response = client.post("/themes/override", json=payload)
        assert response.status_code == 200
        assert "error" in response.json()
        assert "Failed to apply overrides" in response.json()["error"]
        
        assert store.get_critical_open_count() >= old_count
        entries = store.get_entries_by_file("backend/routers/themes_router.py")
        if len(entries) == 0:
            entries = store.get_entries_by_file("routers/themes_router.py")
        assert len(entries) > 0
        apply_entries = [e for e in entries if "Apply overrides exception" in e.notes]
        assert len(apply_entries) > 0
        assert apply_entries[0].category == "CRITICAL_ROUTER" 

@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_override_set_overrides_tdr_exception(mock_tdr_class):
    # TechnicalDebtStore 自体が例外を投げるケースをモックして、tdr_err 例外ハンドラをカバー
    mock_tdr_class.side_effect = RuntimeError("TDR registry failure")
    
    with patch("template_config.template_config") as mock_template_config:
        mock_template_config.is_active = True
        mock_template_config.template_id = "nhk_documentary"
        mock_template_config.set_overrides.side_effect = ValueError("Failed to set values")
        
        payload = {"overrides": {"subtitle_rules": {"font_size_min_px": 48}}}
        response = client.post("/themes/override", json=payload)
        assert response.status_code == 200
        assert "error" in response.json()
        assert "Failed to apply overrides" in response.json()["error"]

@patch("template_config.template_config")
def test_override_unexpected_exception(mock_template_config):
    type(mock_template_config).is_active = property(fget=MagicMock(side_effect=RuntimeError("Unexpected runtime error")))
    
    payload = {"overrides": {}}
    response = client.post("/themes/override", json=payload)
    assert response.status_code == 500
    assert "Unexpected runtime error" in response.json()["detail"]

@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_override_unexpected_exception_tdr_exception(mock_tdr_class):
    mock_tdr_class.side_effect = RuntimeError("TDR registry failure")
    
    with patch("template_config.template_config") as mock_template_config:
        type(mock_template_config).is_active = property(fget=MagicMock(side_effect=RuntimeError("Unexpected runtime error")))
        
        payload = {"overrides": {}}
        response = client.post("/themes/override", json=payload)
        assert response.status_code == 500
        assert "Unexpected runtime error" in response.json()["detail"]

@patch("template_recommender.template_recommender")
def test_recommend_unexpected_exception(mock_recommender):
    mock_recommender.recommend.side_effect = RuntimeError("AI recommendation engine panic")
    payload = {
        "segments": [{"start": 1.0, "end": 2.0}],
        "total_duration_seconds": 10.0
    }
    response = client.post("/themes/recommend", json=payload)
    assert response.status_code == 500
    assert "AI recommendation engine panic" in response.json()["detail"]

@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_recommend_unexpected_exception_tdr_exception(mock_tdr_class):
    mock_tdr_class.side_effect = RuntimeError("TDR registry failure")
    
    with patch("template_recommender.template_recommender") as mock_recommender:
        mock_recommender.recommend.side_effect = RuntimeError("AI recommendation engine panic")
        payload = {
            "segments": [{"start": 1.0, "end": 2.0}],
            "total_duration_seconds": 10.0
        }
        response = client.post("/themes/recommend", json=payload)
        assert response.status_code == 500
        assert "AI recommendation engine panic" in response.json()["detail"]

@patch("template_config.template_config")
def test_apply_template_config_http_exception(mock_template_config):
    mock_template_config.set_active_template.side_effect = HTTPException(status_code=502, detail="Upstream configuration error")
    
    payload = {
        "template_id": "nhk_documentary",
        "theme_id": "cool"
    }
    response = client.post("/themes/apply", json=payload)
    assert response.status_code == 502
    assert response.json()["detail"] == "Upstream configuration error"

@patch("template_config.template_config")
def test_override_http_exception(mock_template_config):
    mock_template_config.is_active = True
    mock_template_config.template_id = "nhk_documentary"
    mock_template_config.set_overrides.side_effect = HTTPException(status_code=400, detail="HTTP specific error")
    
    payload = {"overrides": {"subtitle_rules": {"font_size_min_px": 48}}}
    response = client.post("/themes/override", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "HTTP specific error"

@patch("tempfile.mkstemp")
def test_record_template_selection_atomic_write_exception(mock_mkstemp):
    mock_mkstemp.side_effect = OSError("No space left on device")
    themes_router._record_template_selection("nhk_documentary", "warm")


@patch("os.replace")
def test_record_template_selection_atomic_write_replace_exception(mock_replace):
    mock_replace.side_effect = OSError("Permission denied")
    themes_router._record_template_selection("nhk_documentary", "warm")
