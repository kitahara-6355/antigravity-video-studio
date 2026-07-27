import sys
import os
import json
import pytest
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルートとアーカイブディレクトリを sys.path に追加
ROOT_DIR = Path(__file__).parent.parent.resolve()
ARCHIVE_DIR = ROOT_DIR / "backend" / "archives" / "archive_stable_v3.0_20260118_0953"

sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ARCHIVE_DIR))

# branding_manager をインポート
import branding_manager
from branding_manager import BrandingManager

@pytest.fixture
def mock_branding_env(tmp_path, monkeypatch):
    """
    一時ディレクトリを使用して、BrandingManagerが参照するJSONファイルパスをモックする。
    """
    archive_branding_dir = tmp_path / "branding"
    archive_branding_dir.mkdir()
    
    # 必要なJSONファイルをダミーで配置
    constitution_data = {
        "channel_name": "TestChannel",
        "target_audience": "TestAudience",
        "brand_personality": {"tone": "Friendly", "keywords": ["test"]},
        "visual_identity": {"style_prompt": "TestStyle"},
        "evolution_vision": "Initial vision",
        "content_policy": ["Avoid spam"]
    }
    strategy_data = {
        "current_phase": "Phase 1",
        "current_mission": {
            "focus": "TestFocus",
            "target_value": "100",
            "advice": "TestAdvice"
        }
    }
    user_model_data = {
        "name": "TestStudio",
        "profiles": {
            "admin": {
                "name": "AdminUser",
                "ranks": {
                    "tech_rank": {
                        "level": "Novice",
                        "xp": 50
                    }
                }
            },
            "owner": {
                "name": "OwnerUser",
                "ranks": {
                    "biz_rank": {
                        "level": "Novice",
                        "xp": 50
                    }
                }
            }
        },
        "collaborative_settings": {
            "auto_pilot_ratio": 0.9
        }
    }
    
    constitution_path = archive_branding_dir / "constitution.json"
    strategy_path = archive_branding_dir / "strategy.json"
    user_model_path = archive_branding_dir / "user_model.json"
    evolution_log_path = archive_branding_dir / "evolution_log.json"
    
    with open(constitution_path, "w", encoding="utf-8") as f:
        json.dump(constitution_data, f)
    with open(strategy_path, "w", encoding="utf-8") as f:
        json.dump(strategy_data, f)
    with open(user_model_path, "w", encoding="utf-8") as f:
        json.dump(user_model_data, f)
    with open(evolution_log_path, "w", encoding="utf-8") as f:
        json.dump({"entries": [], "philosophies": []}, f)
        
    monkeypatch.setattr(branding_manager, "BRANDING_DIR", str(archive_branding_dir))
    monkeypatch.setattr(branding_manager, "CONSTITUTION_PATH", str(constitution_path))
    monkeypatch.setattr(branding_manager, "STRATEGY_PATH", str(strategy_path))
    monkeypatch.setattr(branding_manager, "USER_MODEL_PATH", str(user_model_path))
    
    # ContextResolver.get_deep_context_block もモック
    monkeypatch.setattr(
        "branding_manager.ContextResolver.get_deep_context_block",
        lambda path, vision: "mocked deep context"
    )
    
    yield archive_branding_dir

def test_load_json_success(mock_branding_env):
    bm = BrandingManager()
    assert bm.constitution["channel_name"] == "TestChannel"
    assert bm.strategy["current_phase"] == "Phase 1"
    assert bm.user_model["name"] == "TestStudio"

def test_load_json_file_not_found(mock_branding_env, monkeypatch):
    monkeypatch.setattr(branding_manager, "CONSTITUTION_PATH", "non_existent_file.json")
    bm = BrandingManager()
    assert bm.constitution == {}

def test_load_json_decode_error(mock_branding_env, monkeypatch):
    invalid_json_file = mock_branding_env / "invalid.json"
    with open(invalid_json_file, "w", encoding="utf-8") as f:
        f.write("invalid json content")
    monkeypatch.setattr(branding_manager, "CONSTITUTION_PATH", str(invalid_json_file))
    bm = BrandingManager()
    assert bm.constitution == {}

def test_get_context_block(mock_branding_env):
    bm = BrandingManager()
    context = bm.get_context_block()
    assert "TestChannel" in context
    assert "TestAudience" in context
    assert "Friendly" in context
    assert "TestStyle" in context
    assert "Phase 1" in context
    assert "TestFocus" in context
    assert "TestAdvice" in context
    assert "AdminUser" in context
    assert "OwnerUser" in context

def test_get_deep_context(mock_branding_env):
    bm = BrandingManager()
    bm.current_vision = "my vision"
    deep_context = bm.get_deep_context()
    assert deep_context == "mocked deep context"

def test_update_user_rank_tech_rank(mock_branding_env):
    bm = BrandingManager()
    
    # 50 -> 60 XP
    bm.update_user_rank("tech_rank", 10)
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 60
    assert bm.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.9  # 100未満なので0.9
    
    # 60 -> 110 XP
    bm.update_user_rank("tech_rank", 50)
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 110
    assert bm.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.5  # 100以上500未満で0.5
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] == "Editor (Intermediate)"
    
    # 110 -> 510 XP
    bm.update_user_rank("tech_rank", 400)
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 510
    assert bm.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.1  # 500以上で0.1
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] == "Director (Master)"

def test_update_user_rank_biz_rank(mock_branding_env):
    bm = BrandingManager()
    bm.update_user_rank("biz_rank", 20)
    assert bm.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 70

def test_evolve_constitution(mock_branding_env):
    bm = BrandingManager()
    success_event = {
        "type": "test_type",
        "value": "test_value",
        "keyword": "new_keyword"
    }
    bm.evolve_constitution(success_event)
    assert "Success: test_type - test_value" in bm.constitution["evolution_vision"]
    assert "new_keyword" in bm.constitution["brand_personality"]["keywords"]

def test_evolve_constitution_error(mock_branding_env):
    bm = BrandingManager()
    # constitution が None などの場合にエラーログが出力されクラッシュしないことを確認
    bm.constitution = None
    bm.evolve_constitution({"type": "test"})
    # 例外がスローされないことを確認

@patch("branding_manager.decision_logger")
def test_sync_decisions_to_constitution(mock_logger, mock_branding_env):
    bm = BrandingManager()
    
    mock_logger.get_director_preferences.return_value = {
        "こだわり（却下傾向）": {"bad_adjust": 3},
        "好み（承認傾向）": {"good_keyword": 5}
    }
    
    result = bm.sync_decisions_to_constitution()
    assert result["synced"] is True
    assert "content_policy: +'bad_adjust'" in result["changes"]
    assert "keywords: +'good_keyword'" in result["changes"]
    assert "Avoid 'bad_adjust' adjustments; conflicts with director's preferences." in bm.constitution["content_policy"]
    assert "good_keyword" in bm.constitution["brand_personality"]["keywords"]

def test_sync_decisions_to_constitution_no_logger(mock_branding_env, monkeypatch):
    monkeypatch.setattr(branding_manager, "decision_logger", None)
    bm = BrandingManager()
    result = bm.sync_decisions_to_constitution()
    assert result["synced"] is False
    assert result["reason"] == "decision_logger not imported"

@patch("branding_manager.decision_logger")
def test_auto_evolve_all(mock_logger, mock_branding_env):
    bm = BrandingManager()
    mock_logger.get_director_preferences.return_value = {}
    mock_logger.sync_to_soul_narrative.return_value = {"synced": True}
    
    results = bm.auto_evolve_all()
    assert results["decision_sync"]["synced"] is True
    assert results["soul_narrative_sync"]["synced"] is True
    assert results["philosophy_check"]["integrated"] is False

@patch("branding.analytics_manager.analytics_manager")
def test_process_analytics_update(mock_analytics, mock_branding_env):
    bm = BrandingManager()
    mock_analytics.get_my_stats.return_value = {
        "subscribers": 1000,
        "total_views": 10000
    }
    mock_analytics.scout_rivals.return_value = []
    mock_analytics.calculate_gap.return_value = []
    
    result = bm.process_analytics_update()
    assert result["biz_xp"] == 100
    # biz_rank XP = 50 + 50 (change calculated_xp - biz_rank_xp -> 100 - 50 = 50)
    assert bm.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 100
    assert bm.user_model["external_status"]["youtube"]["total_views"] == 10000

def test_update_user_model(mock_branding_env):
    bm = BrandingManager()
    bm.user_model["ai_notes"] = "note1"
    bm.update_user_model("note2")
    assert bm.user_model["ai_notes"] == "note1 note2"

def test_update_strategy(mock_branding_env):
    bm = BrandingManager()
    bm.update_strategy(phase="Phase 2", advise="New Advice")
    assert bm.strategy["current_phase"] == "Phase 2"
    assert bm.strategy["current_mission"]["advice"] == "New Advice"

def test_ingest_report(mock_branding_env):
    bm = BrandingManager()
    # log_evolution をモックして Gemini 呼び出しを回避
    bm.log_evolution = MagicMock()
    
    report_data = {
        "xp_grant": 30,
        "agenda_proposal": "Agenda Item"
    }
    result = bm.ingest_report(report_data)
    assert result["status"] == "success"
    assert result["xp_granted"] == 30
    assert result["agenda"] == "Agenda Item"
    assert bm.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 80

@patch("google.genai.Client")
@patch("model_registry.get_model")
def test_log_evolution_success(mock_get_model, mock_client_cls, mock_branding_env):
    mock_get_model.return_value = "gemini-model"
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "summary": "Growth summary",
        "insight": "Growth insight",
        "stat_changes": ["Tech Rank +10"],
        "new_philosophy_hint": "New Motto"
    })
    mock_client.models.generate_content.return_value = mock_response
    mock_client_cls.return_value = mock_client
    
    bm = BrandingManager()
    bm.api_key = "fake_key"
    
    session_data = {"key": "value"}
    entry = bm.log_evolution(session_data)
    
    assert entry is not None
    assert entry["summary"] == "Growth summary"
    assert entry["new_philosophy_hint"] == "New Motto"
    
    # evolution_log に entries と philosophies が追加されていること
    log_data = bm.get_evolution_log()
    assert len(log_data["entries"]) == 1
    assert len(log_data["philosophies"]) == 1
    assert log_data["philosophies"][0]["philosophy"] == "New Motto"

@patch("google.genai.Client")
@patch("model_registry.get_model")
def test_integrate_philosophies(mock_get_model, mock_client_cls, mock_branding_env):
    mock_get_model.return_value = "gemini-model"
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Integrated Deep Philosophy"
    mock_client.models.generate_content.return_value = mock_response
    mock_client_cls.return_value = mock_client
    
    bm = BrandingManager()
    bm.api_key = "fake_key"
    
    # philosophiesを3件用意する
    evo_log = {
        "entries": [],
        "philosophies": [
            {"philosophy": "p1", "timestamp": "t1", "session_summary": "s1"},
            {"philosophy": "p2", "timestamp": "t2", "session_summary": "s2"},
            {"philosophy": "p3", "timestamp": "t3", "session_summary": "s3"}
        ]
    }
    
    bm._integrate_philosophies(evo_log)
    assert evo_log["integrated_philosophy"] == "Integrated Deep Philosophy"
    assert len(evo_log["integration_history"]) == 1
    assert evo_log["integration_history"][0]["philosophy"] == "Integrated Deep Philosophy"

# --- 新規追加テストケース（不具合検証とログ改善） ---

def test_save_json_creates_directory(mock_branding_env):
    """
    保存先ディレクトリが存在しない場合でも、自動作成されて正常に保存できることを確認する。
    """
    bm = BrandingManager()
    # 存在しないサブディレクトリのパスを指定
    deep_path = os.path.join(str(mock_branding_env), "new_subdir", "test_file.json")
    
    # 修正前は失敗するはず（ディレクトリがないため）だが、修正後は成功する
    bm._save_json(deep_path, {"status": "ok"})
    
    assert os.path.exists(deep_path)
    with open(deep_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["status"] == "ok"

def test_load_json_file_not_found_log(mock_branding_env, caplog):
    """
    ファイル不在時のログレベルが WARNING になっており、ERROR ログが出力されないことを確認する。
    """
    bm = BrandingManager()
    non_existent = os.path.join(str(mock_branding_env), "does_not_exist.json")
    
    with caplog.at_level(logging.WARNING):
        data = bm._load_json(non_existent)
        
    assert data == {}
    
    # WARNING ログが出ていること
    warning_logs = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warning_logs) >= 1
    assert "File not found" in warning_logs[0].message
    
    # ERROR ログが出ていないこと
    error_logs = [rec for rec in caplog.records if rec.levelno == logging.ERROR]
    assert len(error_logs) == 0
