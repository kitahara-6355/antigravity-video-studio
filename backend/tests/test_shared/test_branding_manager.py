"""
M2.5: Branding Manager テスト — 15テスト + 新規画像検証テスト

branding_manager.py のカバレッジ改善および画像バリデーション、画像生成ロジックの改善検証。
"""

import pytest
import json
import sys
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


@pytest.fixture
def branding_dir(tmp_path):
    """テスト用ブランディングディレクトリ"""
    # constitution.json
    constitution = {
        "channel_name": "テストチャンネル",
        "target_audience": "テスト視聴者",
        "brand_personality": {"tone": "professional", "keywords": ["品質"]},
        "visual_identity": {"style_prompt": "modern"},
        "evolution_vision": "",
        "content_policy": [],
    }
    (tmp_path / "constitution.json").write_text(json.dumps(constitution, ensure_ascii=False), encoding="utf-8")

    # strategy.json
    strategy = {
        "current_phase": "Phase 2",
        "current_mission": {"focus": "テスト", "target_value": 100, "advice": "テストアドバイス"},
    }
    (tmp_path / "strategy.json").write_text(json.dumps(strategy, ensure_ascii=False), encoding="utf-8")

    # user_model.json
    user_model = {
        "name": "テストスタジオ",
        "profiles": {
            "admin": {"name": "Admin", "ranks": {"tech_rank": {"level": "Novice", "xp": 50}}},
            "owner": {"name": "Owner", "ranks": {"biz_rank": {"level": "Starter", "xp": 10}}},
        },
        "collaborative_settings": {"auto_pilot_ratio": 0.9},
    }
    (tmp_path / "user_model.json").write_text(json.dumps(user_model, ensure_ascii=False), encoding="utf-8")

    # evolution_log.json
    evo_log = {"entries": [], "philosophies": []}
    (tmp_path / "evolution_log.json").write_text(json.dumps(evo_log, ensure_ascii=False), encoding="utf-8")

    return tmp_path


@pytest.fixture
def manager(branding_dir):
    """テスト用BrandingManager"""
    from branding_manager import BrandingManager
    mgr = BrandingManager.__new__(BrandingManager)
    mgr.constitution = json.loads((branding_dir / "constitution.json").read_text(encoding="utf-8"))
    mgr.strategy = json.loads((branding_dir / "strategy.json").read_text(encoding="utf-8"))
    mgr.user_model = json.loads((branding_dir / "user_model.json").read_text(encoding="utf-8"))
    mgr.api_key = None
    mgr.current_vision = ""
    # _load_jsonと_save_jsonをブランディングディレクトリに紐付け
    mgr._load_json = lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
    mgr._save_json = lambda path, data: Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return mgr, branding_dir


# ============================================================
# BrandingManager テスト
# ============================================================

class TestBrandingManager:
    """BrandingManager: ブランド管理"""

    def test_get_context_block(self, manager):
        """get_context_block: コンテキストブロック生成"""
        mgr, bdir = manager
        # get_philosophies_contextをモック
        mgr.get_philosophies_context = lambda: "テスト哲学"
        ctx = mgr.get_context_block()
        assert "テストチャンネル" in ctx
        assert "BRAND CONSTITUTION" in ctx
        assert "STRATEGIC MISSION" in ctx

    def test_get_philosophies_context_empty(self, manager):
        """get_philosophies_context: 空のevolution_log"""
        mgr, bdir = manager
        BRANDING_DIR = str(bdir)
        with patch("branding_manager.BRANDING_DIR", BRANDING_DIR):
            mgr._load_json = lambda path: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
            ctx = mgr.get_philosophies_context()
        assert "初心者" in ctx or "哲学" in ctx

    def test_get_philosophies_context_with_data(self, manager):
        """get_philosophies_context: 哲学データありの場合"""
        mgr, bdir = manager
        evo_log = {
            "entries": [{"summary": "テスト学び"}],
            "philosophies": [{"philosophy": "テスト哲学1"}],
            "integrated_philosophy": "統合テスト哲学",
        }
        (bdir / "evolution_log.json").write_text(json.dumps(evo_log, ensure_ascii=False), encoding="utf-8")
        with patch("branding_manager.BRANDING_DIR", str(bdir)):
            ctx = mgr.get_philosophies_context()
        assert "統合テスト哲学" in ctx

    def test_update_user_rank(self, manager):
        """update_user_rank: XP更新"""
        mgr, bdir = manager
        with patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")), \
             patch("branding_manager.history_manager") as mock_history:
            mgr.recalculate_automation = MagicMock()
            mgr.update_user_rank("tech_rank", 10)
        assert mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 60

    def test_evolve_constitution(self, manager):
        """evolve_constitution: 憲法進化"""
        mgr, bdir = manager
        with patch("branding_manager.CONSTITUTION_PATH", str(bdir / "constitution.json")), \
             patch("branding_manager.history_manager") as mock_history:
            mgr.evolve_constitution({
                "type": "keyword_discovery",
                "value": "伝統",
                "keyword": "伝統美",
            })
        assert "伝統美" in mgr.constitution["brand_personality"]["keywords"]

    def test_evolve_constitution_no_keyword(self, manager):
        """evolve_constitution: キーワードなし"""
        mgr, bdir = manager
        with patch("branding_manager.CONSTITUTION_PATH", str(bdir / "constitution.json")), \
             patch("branding_manager.history_manager"):
            mgr.evolve_constitution({"type": "test", "value": "v"})
        # エラーなし

    def test_sync_decisions_no_logger(self, manager):
        """sync_decisions_to_constitution: EvolutionTriggerService委譲後の正常系"""
        mgr, bdir = manager
        with patch("branding_manager.decision_logger", None):
            with patch("services.evolution_trigger_service.EvolutionTriggerService") as MockETS:
                MockETS.return_value.evaluate_triggers.return_value = {"fired": [], "skipped": []}
                result = mgr.sync_decisions_to_constitution()
        assert result["synced"] is True
        assert result["delegated_to"] == "EvolutionTriggerService"

    def test_sync_decisions_with_patterns(self, manager):
        """sync_decisions_to_constitution: EvolutionTriggerServiceがトリガー発火"""
        mgr, bdir = manager
        with patch("services.evolution_trigger_service.EvolutionTriggerService") as MockETS:
            MockETS.return_value.evaluate_triggers.return_value = {
                "fired": [
                    {"action": "add_content_policy", "detail": "テンポ重視"},
                    {"action": "add_keyword", "detail": "明るい"},
                ],
                "skipped": [],
            }
            result = mgr.sync_decisions_to_constitution()
        assert result["synced"] is True
        assert len(result["changes"]) > 0

    def test_ingest_report(self, manager):
        """ingest_report: レポート取り込み"""
        mgr, bdir = manager
        mgr.log_evolution = MagicMock()
        with patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")), \
             patch("branding_manager.history_manager"):
            mgr.recalculate_automation = MagicMock()
            result = mgr.ingest_report({"xp_grant": 20, "agenda_proposal": "テスト"})
        assert result["status"] == "success"
        assert result["xp_granted"] == 20

    def test_get_evolution_log(self, manager):
        """get_evolution_log: 進化ログ取得"""
        mgr, bdir = manager
        with patch("branding_manager.BRANDING_DIR", str(bdir)):
            log = mgr.get_evolution_log()
        assert isinstance(log, dict)

    def test_save_evolution_log(self, manager):
        """save_evolution_log: 進化ログ保存"""
        mgr, bdir = manager
        test_data = {"entries": [{"test": True}]}
        with patch("branding_manager.BRANDING_DIR", str(bdir)):
            mgr.save_evolution_log(test_data)
        saved = json.loads((bdir / "evolution_log.json").read_text(encoding="utf-8"))
        assert saved["entries"][0]["test"] is True

    def test_update_user_model(self, manager):
        """update_user_model: ノート追加"""
        mgr, bdir = manager
        with patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")):
            mgr.update_user_model(note="テストメモ")
        assert "テストメモ" in mgr.user_model.get("ai_notes", "")

    def test_update_strategy(self, manager):
        """update_strategy: 戦略更新"""
        mgr, bdir = manager
        with patch("branding_manager.STRATEGY_PATH", str(bdir / "strategy.json")):
            mgr.update_strategy(phase="Phase 3", advise="新しいアドバイス")
        assert mgr.strategy["current_phase"] == "Phase 3"

    def test_recalculate_automation_novice(self, manager):
        """_recalculate_automation_level: Novice"""
        mgr, bdir = manager
        with patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")), \
             patch("branding_manager.history_manager"):
            mgr._recalculate_automation_level(50)
        assert mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.9

    def test_recalculate_automation_master(self, manager):
        """_recalculate_automation_level: Master"""
        mgr, bdir = manager
        with patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")), \
             patch("branding_manager.history_manager"):
            mgr._recalculate_automation_level(500)
        assert mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.1

    def test_auto_evolve_all(self, manager):
        """auto_evolve_all: 自動進化の統括"""
        mgr, bdir = manager
        mgr.sync_decisions_to_constitution = MagicMock(return_value={"synced": True})
        mgr.get_evolution_log = MagicMock(return_value={"philosophies": []})
        mgr._integrate_philosophies = MagicMock()
        
        mock_logger = MagicMock()
        mock_logger.sync_to_soul_narrative.return_value = {"synced": True}
        
        with patch("branding_manager.decision_logger", mock_logger):
            results = mgr.auto_evolve_all()
            assert results["decision_sync"] == {"synced": True}
            assert results["soul_narrative_sync"] == {"synced": True}
            assert results["philosophy_check"]["integrated"] is False

    def test_log_evolution_success(self, manager):
        """log_evolution: Geminiを用いた進化ログの正常記録"""
        mgr, bdir = manager
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "summary": "成長しました",
            "insight": "より深い理解を得た",
            "stat_changes": ["Tech Rank +10"],
            "new_philosophy_hint": "常にテストすべし"
        })
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("model_registry.get_model", return_value="gemini-2.5-flash"), \
             patch("branding_manager.BRANDING_DIR", str(bdir)):
            
            entry = mgr.log_evolution({"xp_grant": 50})
            assert entry is not None
            assert entry["summary"] == "成長しました"
            
            # evolution_log.json に保存されていることを確認
            evo_log = mgr.get_evolution_log()
            assert len(evo_log["entries"]) > 0
            assert evo_log["philosophies"][0]["philosophy"] == "常にテストすべし"

    def test_integrate_philosophies(self, manager):
        """_integrate_philosophies: 哲学の統合"""
        mgr, bdir = manager
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "統合された新たな哲学"
        mock_client.models.generate_content.return_value = mock_response
        
        evo_log = {
            "philosophies": [
                {"philosophy": "哲学1"},
                {"philosophy": "哲学2"},
                {"philosophy": "哲学3"}
            ]
        }
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("model_registry.get_model", return_value="gemini-2.5-flash"):
            
            mgr._integrate_philosophies(evo_log)
            assert evo_log["integrated_philosophy"] == "統合された新たな哲学"
            assert len(evo_log["integration_history"]) == 1

    def test_process_analytics_update(self, manager):
        """process_analytics_update: アナリティクス更新とBiz XPの加算"""
        mgr, bdir = manager
        
        mock_stats = {
            "subscribers": 1000,
            "total_views": 50000
        }
        mock_rivals = []
        mock_quests = []
        
        mock_analytics = MagicMock()
        mock_analytics.get_my_stats.return_value = mock_stats
        mock_analytics.scout_rivals.return_value = mock_rivals
        mock_analytics.calculate_gap.return_value = mock_quests
        
        mgr.update_user_rank = MagicMock()
        
        with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
             patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")):
            
            result = mgr.process_analytics_update()
            # **外へ出す値は印の集約点を通る**（R1.5-C4・10周目 N-1）。
            # 中身は変えず、作り物であることを名乗る鍵だけが増える
            assert result["stats"]["subscribers"] == 1000
            assert result["stats"]["total_views"] == 50000
            assert result["stats"]["is_real"] is False
            assert result["stats"]["data_source"] == "sample"
            assert result["biz_xp"] == 500  # 50000 / 100 = 500
            mgr.update_user_rank.assert_called_once()



    def test_load_save_json_exceptions(self, manager, tmp_path):
        """_load_json と _save_json の例外ブロックの検証（カバレッジ用）"""
        mgr, bdir = manager
        
        # 1. 存在しないファイル (_load_json FileNotFoundError)
        non_existent = bdir / "non_existent.json"
        # _load_json の実体を使うように再設定
        from branding_manager import BrandingManager
        mgr._load_json = BrandingManager._load_json.__get__(mgr, BrandingManager)
        mgr._save_json = BrandingManager._save_json.__get__(mgr, BrandingManager)
        
        assert mgr._load_json(str(non_existent)) == {}
        
        # 2. 壊れたJSON (_load_json JSONDecodeError)
        broken_json = bdir / "broken.json"
        broken_json.write_text("broken { json", encoding="utf-8")
        assert mgr._load_json(str(broken_json)) == {}
        
        # 3. 読み込みPermissionError (モック)
        with patch("builtins.open", side_effect=PermissionError("Permission Denied")):
            assert mgr._load_json(str(broken_json)) == {}

        # 4. 書き込み時の各種例外
        with patch("builtins.open", side_effect=PermissionError("Write Denied")):
            mgr._save_json(str(non_existent), {})
            
        with patch("builtins.open", side_effect=TypeError("Type Error")):
            mgr._save_json(str(non_existent), {})
            
        with patch("builtins.open", side_effect=OSError("OS Error")):
            mgr._save_json(str(non_existent), {})

    def test_get_philosophies_context_missing_log(self, manager, tmp_path):
        """evolution_log がロードできない場合のフォールバック（107-108行目）"""
        mgr, bdir = manager
        with patch("branding_manager.BRANDING_DIR", str(bdir)):
            # evolution_log.json を削除
            evo_path = bdir / "evolution_log.json"
            if evo_path.exists():
                evo_path.unlink()
            
            from branding_manager import BrandingManager
            mgr._load_json = BrandingManager._load_json.__get__(mgr, BrandingManager)
            
            ctx = mgr.get_philosophies_context()
            assert "初心者" in ctx

    def test_evolve_constitution_exceptions(self, manager):
        """evolve_constitution 内の KeyError, TypeError をカバーする"""
        mgr, bdir = manager
        
        # 1. TypeErrorの誘発
        mgr.constitution = "invalid_string_type"
        # 実装側の _save_json をモック化して余計な書き込みエラーを防ぐ
        mgr._save_json = MagicMock()
        mgr.evolve_constitution({"type": "test", "value": "val"})
        
        # 2. KeyErrorの誘発
        mgr.constitution = {}
        mgr.evolve_constitution({"type": "test", "value": "val"})

    def test_sync_decisions_exceptions(self, manager):
        """sync_decisions_to_constitution 内の ImportError, RuntimeError をカバーする"""
        mgr, bdir = manager
        # sys.modules の EvolutionTriggerService を削除するか、パッチで ImportError を発生させる
        with patch("builtins.__import__", side_effect=ImportError("Mocked Import Error")):
            res = mgr.sync_decisions_to_constitution()
            assert res["synced"] is False
            assert "Mocked Import Error" in res["error"]

    def test_auto_evolve_all_exceptions(self, manager):
        """auto_evolve_all 内の AttributeError, RuntimeError をカバーする"""
        mgr, bdir = manager
        mgr.sync_decisions_to_constitution = MagicMock(return_value={"synced": True})
        mgr.get_evolution_log = MagicMock(return_value={"philosophies": []})
        mgr._integrate_philosophies = MagicMock()
        
        mock_logger = MagicMock()
        mock_logger.sync_to_soul_narrative.side_effect = AttributeError("Mocked Attribute Error")
        
        with patch("branding_manager.decision_logger", mock_logger):
            results = mgr.auto_evolve_all()
            assert "Mocked Attribute Error" in results["soul_narrative_sync"]["error"]

    def test_log_evolution_exceptions(self, manager):
        """log_evolution 内の例外ハンドリング（464-466行目）をカバーする"""
        mgr, bdir = manager
        with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Mocked API Error")):
            res = mgr.log_evolution({"xp_grant": 50})
            assert res is None

    def test_integrate_philosophies_less_than_3(self, manager):
        """_integrate_philosophies で履歴が3件未満の場合の早期リターン（473-474行目）"""
        mgr, bdir = manager
        evo_log = {"philosophies": [{"philosophy": "1つだけ"}]}
        mgr._integrate_philosophies(evo_log)
        assert "integrated_philosophy" not in evo_log

    def test_integrate_philosophies_exceptions(self, manager):
        """_integrate_philosophies 内の例外ハンドリング（512-513行目）をカバーする"""
        mgr, bdir = manager
        evo_log = {
            "philosophies": [
                {"philosophy": "哲学1"},
                {"philosophy": "哲学2"},
                {"philosophy": "哲学3"}
            ]
        }
        with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("Mocked Value Error")):
            mgr._integrate_philosophies(evo_log)
            assert "integrated_philosophy" not in evo_log

    def test_import_error_decision_logger(self):
        import sys
        import importlib
        original_modules = sys.modules.copy()
        sys.modules['decision_logger'] = None
        try:
            import branding_manager
            importlib.reload(branding_manager)
            assert branding_manager.decision_logger is None
        finally:
            sys.modules.update(original_modules)
            import branding_manager
            importlib.reload(branding_manager)

    def test_save_json_success(self, tmp_path):
        from branding_manager import BrandingManager
        mgr = BrandingManager.__new__(BrandingManager)
        mgr._save_json = BrandingManager._save_json.__get__(mgr, BrandingManager)
        test_file = tmp_path / 'test_save.json'
        test_data = {'key': 'value'}
        mgr._save_json(str(test_file), test_data)
        with open(test_file, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded == test_data

    def test_get_deep_context(self, manager):
        mgr, bdir = manager
        import branding_manager
        with patch('branding_manager.ContextResolver') as mock_resolver:
            mock_resolver.get_deep_context_block.return_value = 'deep context block'
            mgr.current_vision = 'my vision'
            res = mgr.get_deep_context()
            assert res == 'deep context block'
            mock_resolver.get_deep_context_block.assert_called_once_with(
                branding_manager.SUBTITLES_PATH,
                'my vision'
            )

    def test_auto_evolve_all_with_integration_trigger(self, manager):
        mgr, bdir = manager
        mgr.sync_decisions_to_constitution = MagicMock(return_value={'synced': True})
        philosophies = [{'philosophy': f'\u54f2\u5b66{i}'} for i in range(10)]
        mgr.get_evolution_log = MagicMock(return_value={'philosophies': philosophies})
        mgr._integrate_philosophies = MagicMock()
        mock_logger = MagicMock()
        mock_logger.sync_to_soul_narrative.return_value = {'synced': True}
        with patch('branding_manager.decision_logger', mock_logger):
            results = mgr.auto_evolve_all()
            assert results['philosophy_check']['integrated'] is True
            assert results['philosophy_check']['count'] == 10
            mgr._integrate_philosophies.assert_called_once()

    def test_recalculate_automation_intermediate_and_missing_key(self, manager):
        mgr, bdir = manager
        if 'collaborative_settings' in mgr.user_model:
            del mgr.user_model['collaborative_settings']
        with patch('branding_manager.USER_MODEL_PATH', str(bdir / 'user_model.json')), \
             patch('branding_manager.history_manager'):
            mgr._recalculate_automation_level(200)
        assert mgr.user_model['collaborative_settings']['auto_pilot_ratio'] == 0.5
        admin_profile = mgr.user_model.get('profiles', {}).get('admin', {})
        assert admin_profile['ranks']['tech_rank']['level'] == 'Editor (Intermediate)'

    def test_log_evolution_initialization_and_client_none(self, manager):
        mgr, bdir = manager
        (bdir / 'evolution_log.json').write_text('{}', encoding='utf-8')
        with patch('gemini_client_factory.get_gemini_client', return_value=None), \
             patch('branding_manager.BRANDING_DIR', str(bdir)):
            res = mgr.log_evolution({'xp_grant': 50})
            assert res is None

    def test_log_evolution_integration_trigger(self, manager):
        mgr, bdir = manager
        evo_log = {'entries': []}
        (bdir / 'evolution_log.json').write_text(json.dumps(evo_log), encoding='utf-8')
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            'summary': '\u6210\u9577\u3057\u307e\u3057\u305f',
            'insight': '\u3088\u308a\u6df1\u3044\u7406\u89e3\u3092\u5f97\u305f',
            'stat_changes': ['Tech Rank +10'],
            'new_philosophy_hint': '\u5e38\u306b\u30c6\u30b9\u30c8\u3059\u3079\u3057'
        })
        mock_client.models.generate_content.return_value = mock_response
        mgr._integrate_philosophies = MagicMock()
        with patch('gemini_client_factory.get_gemini_client', return_value=mock_client), \
             patch('model_registry.get_model', return_value='gemini-2.5-flash'), \
             patch('branding_manager.BRANDING_DIR', str(bdir)):
            mgr.log_evolution({'xp_grant': 50})
            evo_log_loaded = mgr.get_evolution_log()
            assert 'philosophies' in evo_log_loaded
            assert len(evo_log_loaded['philosophies']) == 1
            evo_log_loaded['philosophies'] = [{'philosophy': f'\u54f2\u5b66{i}', 'timestamp': 'time'} for i in range(9)]
            mgr.save_evolution_log(evo_log_loaded)
            mgr.log_evolution({'xp_grant': 50})
            mgr._integrate_philosophies.assert_called_once()

    def test_integrate_philosophies_client_none(self, manager):
        mgr, bdir = manager
        evo_log = {
            'philosophies': [{'philosophy': f'\u54f2\u5b66{i}'} for i in range(5)]
        }
        with patch('gemini_client_factory.get_gemini_client', return_value=None):
            mgr._integrate_philosophies(evo_log)
            assert 'integrated_philosophy' not in evo_log

    def test_robust_guards_with_corrupted_data(self, manager, tmp_path):
        """データ構造が完全に破損している（Noneや別タイプ）場合でもクラッシュせずガードが働くことのテスト"""
        mgr, bdir = manager
        
        # init 時の dict チェックのカバーのために _load_json をモックして None を返させる
        with patch.object(mgr, '_load_json', return_value=None):
            mgr.__init__()
            assert mgr.constitution == {}
            assert mgr.strategy == {}
            assert mgr.user_model == {}

        mgr.__init__() # 通常に戻す

        # 1. user_model が None や不正値の時
        mgr.user_model = None
        mgr.update_user_rank("tech_rank", 10)
        assert isinstance(mgr.user_model, dict)
        assert mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 10
        
        # 1.2. current_xp が数値ではない場合のカバー
        mgr.user_model = {
            "profiles": {
                "admin": {
                    "ranks": {
                        "tech_rank": {
                            "xp": "not_an_int"
                        }
                    }
                }
            }
        }
        mgr.update_user_rank("tech_rank", 10)
        assert mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["xp"] == 10
        
        # 2. _recalculate_automation_level での一部破損
        mgr.user_model = {"profiles": None}
        mgr._recalculate_automation_level(200)
        assert mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.5
        assert mgr.user_model["profiles"]["admin"]["ranks"]["tech_rank"]["level"] == "Editor (Intermediate)"
        
        # 2.2. old_ratio が数値ではない場合のカバー
        mgr.user_model = {
            "collaborative_settings": {
                "auto_pilot_ratio": "not_a_float"
            }
        }
        mgr._recalculate_automation_level(200)
        assert mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.5
        
        # 2.3. recalc での self.user_model=None ガード
        mgr.user_model = None
        mgr._recalculate_automation_level(200)
        assert mgr.user_model["collaborative_settings"]["auto_pilot_ratio"] == 0.5

        # 3. constitution が破損している状態での evolve_constitution
        mgr.constitution = None
        mgr.evolve_constitution({"type": "keyword", "value": "val", "keyword": "KW"})
        assert isinstance(mgr.constitution, dict)
        assert "KW" in mgr.constitution["brand_personality"]["keywords"]
        
        # 3.2. constitution 内の一部データ破損による TypeError 発生と except キャッチのカバー
        mgr.constitution = {"evolution_vision": {}}
        mgr.evolve_constitution({"type": "keyword", "value": "val"})
        
        # 4. analytics_update で analytics_manager が None などを返す場合
        mock_analytics = MagicMock()
        mock_analytics.get_my_stats.return_value = None  # 不正データ
        mock_analytics.scout_rivals.return_value = []
        mock_analytics.calculate_gap.return_value = []
        
        mgr.user_model = {}
        with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
             patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")):
            res = mgr.process_analytics_update()
            # 印の集約点を通るので鍵が増える（R1.5-C4・10周目 N-1）
            assert res["stats"]["subscribers"] == 0
            assert res["stats"]["total_views"] == 0
            assert res["stats"]["is_real"] is False
            assert res["biz_xp"] == 0

        # 4.2. stats 内の数値が文字列などの場合
        mock_analytics.get_my_stats.return_value = {"subscribers": "invalid", "total_views": "invalid"}
        mgr.user_model = {}
        with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
             patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")):
            res = mgr.process_analytics_update()
            assert res["biz_xp"] == 0
            
        # 4.3. biz_rank_xp が数値ではない場合
        mgr.user_model = {
            "profiles": {
                "owner": {
                    "ranks": {
                        "biz_rank": {
                            "xp": "invalid"
                        }
                    }
                }
            }
        }
        mock_analytics.get_my_stats.return_value = {"subscribers": 100, "total_views": 1000}
        with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
             patch("branding_manager.USER_MODEL_PATH", str(bdir / "user_model.json")):
            res = mgr.process_analytics_update()
            assert mgr.user_model["profiles"]["owner"]["ranks"]["biz_rank"]["xp"] == 10

    # ============================================================
    # 新規追加：サムネイル・プレビュー画像品質検証テスト
    # ============================================================

    def test_validate_image_quality_success(self, manager, tmp_path):
        """validate_image_quality: 正常画像データの検証"""
        mgr, bdir = manager
        
        from PIL import Image
        import io
        img = Image.new("RGB", (1280, 720), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        
        # bytes入力での検証
        result = mgr.validate_image_quality(img_bytes)
        assert result["valid"] is True
        assert result["width"] == 1280
        assert result["height"] == 720
        assert abs(result["aspect_ratio"] - 16/9) < 0.01
        
        # ファイルパス入力での検証
        img_file = tmp_path / "test_thumb.png"
        img_file.write_bytes(img_bytes)
        
        result_file = mgr.validate_image_quality(str(img_file))
        assert result_file["valid"] is True
        
    def test_validate_image_quality_low_resolution(self, manager):
        """validate_image_quality: 解像度不足の画像"""
        mgr, bdir = manager
        from PIL import Image
        import io
        img = Image.new("RGB", (640, 360), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            mgr.validate_image_quality(img_bytes)
            
    def test_validate_image_quality_bad_aspect_ratio(self, manager):
        """validate_image_quality: アスペクト比異常"""
        mgr, bdir = manager
        from PIL import Image
        import io
        img = Image.new("RGB", (1280, 960), color="blue") # 4:3
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            mgr.validate_image_quality(img_bytes)
            
    def test_validate_image_quality_exceeds_size(self, manager, tmp_path):
        """validate_image_quality: ファイルサイズ制限超過"""
        mgr, bdir = manager
        img_file = tmp_path / "huge.png"
        img_file.write_bytes(b"dummy")
        
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
            with pytest.raises(ValueError, match="File size exceeds or equals 4MB limit"):
                mgr.validate_image_quality(str(img_file))
                
    def test_validate_image_quality_invalid_input(self, manager):
        """validate_image_quality: 無効な引数型や破損したデータ"""
        mgr, bdir = manager
        with pytest.raises(TypeError, match="Input must be a file path or bytes object"):
            mgr.validate_image_quality(123)
            
        with pytest.raises(IOError, match="Failed to decode image data"):
            mgr.validate_image_quality(b"invalid corrupt bytes data")

    def test_generate_and_validate_thumbnail_success(self, manager):
        """generate_and_validate_thumbnail: 正常なサムネイル生成"""
        mgr, bdir = manager
        
        from PIL import Image
        import io
        import base64
        img = Image.new("RGB", (1280, 720), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        valid_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        mock_generator = MagicMock()
        async def mock_generate(*args, **kwargs):
            return [{
                "concept_name": "Test Concept",
                "description": "Test Desc",
                "image_base64": valid_b64,
                "ctr_score": 6.8
            }]
        mock_generator.generate = mock_generate
        
        with patch("thumbnail_engine.generator.ThumbnailGenerator", return_value=mock_generator):
            res = mgr.generate_and_validate_thumbnail("Test Title", "Test Desc")
            assert res["status"] == "success"
            assert res["concept_name"] == "Test Concept"
            assert res["validation"]["valid"] is True

    def test_generate_and_validate_thumbnail_fallback_on_api_error(self, manager):
        """generate_and_validate_thumbnail: APIエラー時のフォールバック"""
        mgr, bdir = manager
        
        mock_generator = MagicMock()
        async def mock_generate(*args, **kwargs):
            raise RuntimeError("API Connection Failed")
        mock_generator.generate = mock_generate
        
        with patch("thumbnail_engine.generator.ThumbnailGenerator", return_value=mock_generator):
            res = mgr.generate_and_validate_thumbnail("Test Title", "Test Desc")
            assert res["status"] == "fallback"
            assert res["concept_name"] == "Standard Fallback Concept"
            assert "validation" in res
            assert res["validation"]["valid"] is True
            assert res["validation"]["width"] == 1280
            assert res["validation"]["height"] == 720

    def test_generate_and_validate_thumbnail_fallback_on_validation_failure(self, manager):
        """generate_and_validate_thumbnail: バリデーション失敗（解像度不足）時のフォールバック"""
        mgr, bdir = manager
        
        from PIL import Image
        import io
        import base64
        img = Image.new("RGB", (640, 360), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        invalid_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        mock_generator = MagicMock()
        async def mock_generate(*args, **kwargs):
            return [{
                "concept_name": "Low Res Concept",
                "description": "Invalid resolution",
                "image_base64": invalid_b64,
                "ctr_score": 3.0
            }]
        mock_generator.generate = mock_generate
        
        with patch("thumbnail_engine.generator.ThumbnailGenerator", return_value=mock_generator):
            res = mgr.generate_and_validate_thumbnail("Test Title", "Test Desc")
            assert res["status"] == "fallback"
            assert res["concept_name"] == "Standard Fallback Concept"
            assert res["validation"]["width"] == 1280

    # ============================================================
    # 新規追加：解像度/アスペクト比/ファイルサイズの境界値検証テスト
    # ============================================================

    def test_validate_image_quality_boundary_file_size(self, manager, tmp_path):
        """validate_image_quality: ファイルサイズの境界条件検証 (ちょうど4MB、わずかに超過)"""
        mgr, bdir = manager
        img_file = tmp_path / "boundary_size.png"
        
        # ちょうど4MBのダミーバイナリ (4 * 1024 * 1024 bytes)
        limit_size = 4 * 1024 * 1024
        
        from PIL import Image
        import io
        img = Image.new("RGB", (1280, 720), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        real_png_bytes = buf.getvalue()
        
        # ファイルサイズ制限を超えるためのパディング追加
        pad_size_exact = limit_size - len(real_png_bytes)
        img_file.write_bytes(real_png_bytes + b"0" * pad_size_exact)
        
        # モックでサイズと画像の挙動をシミュレート
        with patch("pathlib.Path.stat") as mock_stat:
            # 4MB未満の境界値 (limit_size - 1) -> 通過するはず
            mock_stat.return_value.st_size = limit_size - 1
            with patch("PIL.Image.open") as mock_open:
                mock_img = MagicMock()
                mock_img.size = (1280, 720)
                mock_open.return_value.__enter__.return_value = mock_img
                
                result = mgr.validate_image_quality(str(img_file))
                assert result["valid"] is True
                assert result["size_bytes"] == limit_size - 1
                
            # ちょうど4MB (境界値) -> エラーになるはず
            mock_stat.return_value.st_size = limit_size
            with pytest.raises(ValueError, match="File size exceeds or equals 4MB limit"):
                mgr.validate_image_quality(str(img_file))

    def test_validate_image_quality_boundary_resolution(self, manager):
        """validate_image_quality: 解像度の境界条件検証 (1280x720ちょうど、それ未満)"""
        mgr, bdir = manager
        from PIL import Image
        import io
        
        # 1280x720 ちょうど (境界値)
        img_exact = Image.new("RGB", (1280, 720), color="blue")
        buf_exact = io.BytesIO()
        img_exact.save(buf_exact, format="PNG")
        
        result = mgr.validate_image_quality(buf_exact.getvalue())
        assert result["valid"] is True
        
        # 幅が1画素足りない場合 (1279x720)
        img_narrow = Image.new("RGB", (1279, 720), color="blue")
        buf_narrow = io.BytesIO()
        img_narrow.save(buf_narrow, format="PNG")
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            mgr.validate_image_quality(buf_narrow.getvalue())
            
        # 高さが1画素足りない場合 (1280x719)
        img_short = Image.new("RGB", (1280, 719), color="blue")
        buf_short = io.BytesIO()
        img_short.save(buf_short, format="PNG")
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            mgr.validate_image_quality(buf_short.getvalue())

    def test_validate_image_quality_various_ratios(self, manager):
        """validate_image_quality: 許容されるアスペクト比と許容されないアスペクト比の境界検証"""
        mgr, bdir = manager
        from PIL import Image
        import io
        
        # 16:9 ちょうど (1.777...)
        img_perfect = Image.new("RGB", (1920, 1080), color="blue")
        buf_perfect = io.BytesIO()
        img_perfect.save(buf_perfect, format="PNG")
        assert mgr.validate_image_quality(buf_perfect.getvalue())["valid"] is True
        
        # 16:9 からのズレが許容範囲内 (例: 1.765 => 1500x850 は比率1.7647, 誤差 0.013 < 0.02)
        img_ok = Image.new("RGB", (1500, 850), color="blue")
        buf_ok = io.BytesIO()
        img_ok.save(buf_ok, format="PNG")
        assert mgr.validate_image_quality(buf_ok.getvalue())["valid"] is True
        
        # 16:9 からのズレが許容範囲外 (例: 16:10 = 1.60 => 1280x800 は比率1.60, 誤差 0.177 > 0.02)
        img_bad = Image.new("RGB", (1280, 800), color="blue")
        buf_bad = io.BytesIO()
        img_bad.save(buf_bad, format="PNG")
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            mgr.validate_image_quality(buf_bad.getvalue())

    def test_generate_fallback_image_bytes_quality(self, manager):
        """_generate_fallback_image_bytes: 高品質なフォールバック画像生成とその検証"""
        mgr, bdir = manager
        
        # タイトルを指定して高品質なフォールバック画像を生成
        fallback_bytes = mgr._generate_fallback_image_bytes("テスト動画タイトル")
        
        # 生成された画像が検証基準を完全に満たしているかチェック
        result = mgr.validate_image_quality(fallback_bytes)
        assert result["valid"] is True
        assert result["width"] == 1280
        assert result["height"] == 720
        assert abs(result["aspect_ratio"] - 1.777) < 0.01
        
        # 画像フォーマットが正常にデコードできることをPillowで再検証
        from PIL import Image
        import io
        with Image.open(io.BytesIO(fallback_bytes)) as img:
            assert img.format == "JPEG"
            assert img.size == (1280, 720)

    @pytest.mark.asyncio
    async def test_resolve_thumbnail_task_success(self, manager, tmp_path):
        """resolve_thumbnail_task: StageBoundAgent と連携した正常系タスクの完了を検証"""
        mgr, bdir = manager
        import asyncio
        from pathlib import Path
        from agents.stage_bound_agent import StageBoundAgent
        
        # テスト用の一時ファイルDBを使用
        db_file = tmp_path / "tasks_success.db"
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
        
        # タスクを登録
        task_id = "test_task_success"
        await agent.register_task(task_id, initial_status="READY", max_retries=1)
        
        # mgr.resolve_thumbnail_task を使ってタスクを処理させる
        output_dir = tmp_path / "test_out"
        
        async def process_func(tid):
            return await mgr.resolve_thumbnail_task(tid, output_dir=str(output_dir))
            
        await agent.start(process_func)
        
        # 完了まで待つ
        for _ in range(20):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        await agent.stop()
        
        # 結果の検証 (stop後もファイルDBなので検証可能)
        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"
        
        # DBから結果を取得
        conn = agent._get_conn()
        cursor = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_str = row[0]
        error_str = row[1]
        assert error_str is None
        assert result_str is not None
        
        result_info = json.loads(result_str)
        assert "path" in result_info
        assert "width" in result_info
        assert "height" in result_info
        assert "size_bytes" in result_info
        
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # 生成された画像が正常で破損していないことを Pillow でロードして検証
        from PIL import Image
        img_path = Path(result_info["path"])
        assert img_path.exists()
        with Image.open(img_path) as img:
            img.verify()
        with Image.open(img_path) as img:
            img.load()
            assert img.size == (1280, 720)
        agent._close_conn(conn)

    @pytest.mark.asyncio
    async def test_resolve_thumbnail_task_retry_and_fail(self, manager, tmp_path):
        """resolve_thumbnail_task: 例外発生時の自動リトライと最終失敗状態の検証"""
        mgr, bdir = manager
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        
        db_file = tmp_path / "tasks_fail.db"
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
        task_id = "test_task_retry_fail"
        
        # リトライ上限を2回に設定 (初期実行1回 + リトライ2回 = 計3回実行される)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)
        
        call_count = 0
        
        async def failing_process(tid):
            nonlocal call_count
            call_count += 1
            # 意図的に例外をスローして失敗させる
            raise OSError("Simulated filesystem full error")
            
        await agent.start(failing_process)
        
        # 完了（FAILED）まで十分な時間待つ
        for _ in range(30):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)
            
        await agent.stop()
        
        status = await agent.get_task_status(task_id)
        assert status == "FAILED"
        
        # 3回呼び出されたことを検証 (1回目 + 2回リトライ)
        assert call_count == 3
        
        # DBにエラーメッセージが記録されていることを確認
        conn = agent._get_conn()
        cursor = conn.execute("SELECT error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert "Simulated filesystem full error" in row[0]
        assert row[1] == 2  # retry_count が上限に達していること
        agent._close_conn(conn)
