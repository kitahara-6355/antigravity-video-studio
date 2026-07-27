import pytest
import sys
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# モジュールインポート前のモック設定
os.environ["GOOGLE_API_KEY"] = "mock_api_key"

# テスト対象モジュールのインポート
import importlib.util
module_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "branding_manager.py"
spec = importlib.util.spec_from_file_location("branding_manager_archive", str(module_path))
bm_mod = importlib.util.module_from_spec(spec)
sys.modules["branding_manager_archive"] = bm_mod
spec.loader.exec_module(bm_mod)

BrandingManager = bm_mod.BrandingManager

# モックの作成
@pytest.fixture
def mock_branding_manager():
    # 各JSONロードをモックして初期化
    mock_constitution = {
        "channel_name": "TestChannel",
        "target_audience": "Tech",
        "brand_personality": {"tone": "Friendly", "keywords": ["tech"]},
        "visual_identity": {"style_prompt": "modern"},
        "evolution_vision": ""
    }
    mock_strategy = {
        "current_phase": "Phase 1",
        "current_mission": {"focus": "Growth", "target_value": "100", "advice": "Work hard"}
    }
    mock_user_model = {
        "profiles": {
            "admin": {
                "name": "Admin",
                "ranks": {
                    "tech_rank": {
                        "level": "Novice",
                        "xp": 20
                    }
                }
            },
            "owner": {
                "name": "Owner",
                "ranks": {
                    "biz_rank": {
                        "level": "Novice",
                        "xp": 0
                    }
                }
            }
        },
        "collaborative_settings": {
            "auto_pilot_ratio": 0.9
        }
    }

    with patch("branding_manager_archive.BrandingManager._load_json") as mock_load:
        # ロード順に合わせてモックの戻り値を設定
        mock_load.side_effect = lambda path: (
            mock_constitution if "constitution" in str(path)
            else mock_strategy if "strategy" in str(path)
            else mock_user_model if "user_model" in str(path)
            else {}
        )
        with patch("branding_manager_archive.BrandingManager._save_json"):
            # history_manager やその他の依存をパッチ
            with patch("branding_manager_archive.history_manager"):
                bm = BrandingManager()
                yield bm

def test_archive_bm_init(mock_branding_manager):
    assert mock_branding_manager is not None
    assert mock_branding_manager.constitution["channel_name"] == "TestChannel"

def test_archive_bm_update_user_rank_tech(mock_branding_manager):
    # update_user_rank("tech_rank", 10) を呼び出すと _recalculate_automation_level が呼び出されることをテスト
    # recalculate_automation が typo であったため、修正後は _recalculate_automation_level が呼ばれてエラーが起きない
    mock_branding_manager.update_user_rank("tech_rank", 10)
    assert mock_branding_manager.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 30

def test_archive_bm_process_analytics_update(mock_branding_manager):
    # process_analytics_update で KeyError が発生しないことをテスト
    mock_stats = {"subscribers": 100, "total_views": 1000}
    mock_rivals = []
    mock_quests = []
    
    with patch("branding.analytics_manager.analytics_manager") as mock_analytics:
        mock_analytics.get_my_stats.return_value = mock_stats
        mock_analytics.scout_rivals.return_value = mock_rivals
        mock_analytics.calculate_gap.return_value = mock_quests
        
        result = mock_branding_manager.process_analytics_update()
        assert result["biz_xp"] == 10
        # user_model が正しく更新されたこと
        assert mock_branding_manager.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 10

def test_archive_bm_load_json_errors(caplog):
    import logging
    # モックされていない BrandingManager をインスタンス化
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        bm = BrandingManager()
        # 初期化時に constitution, strategy, user_model が存在しないため、警告ログが出力される
        assert any("File not found" in record.message for record in caplog.records)

    # さらに個別に存在しないファイルをテスト
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        res = bm._load_json("another_non_existent_file.json")
        assert res == {}
        assert any("File not found" in record.message for record in caplog.records)
        assert any("another_non_existent_file.json" in record.message for record in caplog.records)

    # 不正なJSON
    caplog.clear()
    with patch("builtins.open", mock_open(read_data="invalid json")):
        with caplog.at_level(logging.ERROR):
            res = bm._load_json("invalid.json")
            assert res == {}
            assert any("Invalid JSON format" in record.message for record in caplog.records)

def test_archive_bm_save_json_error(caplog):
    import logging
    bm = BrandingManager()
    # 無効なJSONデータ（シリアライズできないオブジェクトなど）
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        bm._save_json("output.json", object())
        assert any("Type error during JSON serialization" in record.message for record in caplog.records)

def test_archive_bm_evolve_constitution_error(mock_branding_manager, caplog):
    import logging
    # constitution が None の場合に AttributeError が発生する状況をモック
    original_constitution = mock_branding_manager.constitution
    mock_branding_manager.constitution = None
    try:
        with caplog.at_level(logging.ERROR):
            mock_branding_manager.evolve_constitution({"type": "test"})
            # エラーログに 'Evolution error' と例外の詳細が含まれていること
            assert any("Evolution error" in record.message for record in caplog.records)
    finally:
        mock_branding_manager.constitution = original_constitution

def test_archive_bm_sync_decisions_error(mock_branding_manager, caplog):
    import logging
    # decision_logger のモックが例外を投げるように設定
    with patch("branding_manager_archive.decision_logger") as mock_dec_logger:
        mock_dec_logger.get_director_preferences.side_effect = RuntimeError("Mock error")
        with caplog.at_level(logging.ERROR):
            res = mock_branding_manager.sync_decisions_to_constitution()
            assert res == {"synced": False, "error": "Mock error"}
            assert any("Decision sync error" in record.message for record in caplog.records)

def test_archive_bm_log_evolution_error(mock_branding_manager, caplog):
    import logging
    # APIキーが無効または何らかの要因で例外が発生した場合
    with patch("google.genai.Client", side_effect=RuntimeError("API Error")):
        with caplog.at_level(logging.ERROR):
            res = mock_branding_manager.log_evolution({"test": "data"})
            assert res is None
            assert any("Failed to log evolution" in record.message for record in caplog.records)



def test_archive_bm_auto_evolve_all(mock_branding_manager):
    # auto_evolve_all のテスト
    # philosophies が 10件ある場合、統合と保存が行われることをテスト
    
    mock_evo_log = {
        "philosophies": [{"philosophy": f"philosophy {i}"} for i in range(10)],
        "entries": []
    }
    
    with patch.object(mock_branding_manager, "get_evolution_log", return_value=mock_evo_log):
        with patch.object(mock_branding_manager, "save_evolution_log") as mock_save:
            with patch.object(mock_branding_manager, "_integrate_philosophies") as mock_integrate:
                with patch.object(mock_branding_manager, "sync_decisions_to_constitution", return_value={"synced": True}):
                    res = mock_branding_manager.auto_evolve_all()
                    
                    assert res["philosophy_check"] == {"integrated": True, "count": 10}
                    mock_integrate.assert_called_once_with(mock_evo_log)
                    mock_save.assert_called_once_with(mock_evo_log)

def test_archive_bm_auto_evolve_all_no_integration(mock_branding_manager):
    # philosophies が 5件の場合、統合も保存も行われないことをテスト
    
    mock_evo_log = {
        "philosophies": [{"philosophy": f"philosophy {i}"} for i in range(5)],
        "entries": []
    }
    
    with patch.object(mock_branding_manager, "get_evolution_log", return_value=mock_evo_log):
        with patch.object(mock_branding_manager, "save_evolution_log") as mock_save:
            with patch.object(mock_branding_manager, "_integrate_philosophies") as mock_integrate:
                with patch.object(mock_branding_manager, "sync_decisions_to_constitution", return_value={"synced": True}):
                    res = mock_branding_manager.auto_evolve_all()
                    
                    assert res["philosophy_check"] == {"integrated": False, "count": 5}
                    mock_integrate.assert_not_called()
                    mock_save.assert_not_called()




def test_archive_bm_additional_exceptions(caplog):
    import logging
    from unittest.mock import patch
    
    bm = BrandingManager()
    
    # 1. _load_json で OSError が発生した場合のテスト
    with patch("builtins.open", side_effect=OSError("Mock OS Error")):
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            res = bm._load_json("dummy_path.json")
            assert res == {}
            assert any("OS error" in record.message for record in caplog.records)

    # 2. _save_json で ValueError が発生した場合のテスト
    with patch("json.dump", side_effect=ValueError("Mock Value Error")):
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            bm._save_json("dummy_path.json", {})
            assert any("Value error" in record.message for record in caplog.records)

def test_archive_bm_auto_evolve_attribute_error(mock_branding_manager, caplog):
    import logging
    from unittest.mock import patch
    
    # 3. auto_evolve_all 内で decision_logger.sync_to_soul_narrative が AttributeError を起こした場合のテスト
    with patch("branding_manager_archive.decision_logger") as mock_dec_logger:
        mock_dec_logger.sync_to_soul_narrative.side_effect = AttributeError("Mock Attribute Error")
        mock_branding_manager.api_key = "mock_key"
        mock_evo_log = {"philosophies": [], "entries": []}
        with patch.object(mock_branding_manager, "get_evolution_log", return_value=mock_evo_log):
            with patch.object(mock_branding_manager, "sync_decisions_to_constitution", return_value={"synced": True}):
                caplog.clear()
                with caplog.at_level(logging.ERROR):
                    res = mock_branding_manager.auto_evolve_all()
                    assert "error" in res["soul_narrative_sync"]
                    assert any("Soul narrative sync error" in record.message for record in caplog.records)

def test_archive_bm_update_user_model(mock_branding_manager):
    # ai_notes にノートが追記されることをテスト
    mock_branding_manager.user_model["ai_notes"] = "Existing Note."
    mock_branding_manager.update_user_model("Additional Note.")
    assert "Existing Note. Additional Note." in mock_branding_manager.user_model["ai_notes"]

def test_archive_bm_update_strategy(mock_branding_manager):
    # strategy が更新されることをテスト
    mock_branding_manager.update_strategy(phase="Phase 999", advise="Think different")
    assert mock_branding_manager.strategy["current_phase"] == "Phase 999"
    assert mock_branding_manager.strategy["current_mission"]["advice"] == "Think different"

def test_archive_bm_ingest_report(mock_branding_manager):
    # ingest_report の挙動をテスト
    report_data = {
        "xp_grant": 30,
        "agenda_proposal": "Let's discuss next-gen style"
    }
    
    with patch.object(mock_branding_manager, "log_evolution") as mock_log:
        res = mock_branding_manager.ingest_report(report_data)
        assert res["status"] == "success"
        assert res["xp_granted"] == 30
        assert res["agenda"] == "Let's discuss next-gen style"
        mock_log.assert_called_once_with(report_data)
