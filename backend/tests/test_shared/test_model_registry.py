"""
M2.5: Model Registry テスト — 15テスト

model_registry.py (198 stmts, 134 missed) のカバレッジ改善。
ModelRegistry の全メソッドを網羅: get_model_for_task, fallback, deprecation, plugin登録。

外部依存: model_config.json → モックconfig, Gemini API → パッチ。
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import date, timedelta

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


@pytest.fixture
def fresh_registry(tmp_path):
    """シングルトンをリセットした新規ModelRegistry"""
    from model_registry import ModelRegistry
    ModelRegistry._instance = None
    ModelRegistry._available_models_cache = None
    ModelRegistry._cache_timestamp = None

    config = {
        "version": "test",
        "default_model": "gemini-2.5-flash",
        "task_mapping": {
            "subtitle_split": "gemini-2.5-flash",
            "quality_gate": "gemini-2.5-pro",
            "director": "gemini-2.5-pro",
        },
        "models": {
            "gemini-2.5-flash": {
                "status": "active",
                "description": "高速モデル",
                "use_cases": ["subtitle_split"],
                "cost_tier": "low",
                "fallback": None,
            },
            "gemini-2.5-pro": {
                "status": "active",
                "description": "高精度モデル",
                "use_cases": ["quality_gate", "director"],
                "cost_tier": "high",
                "fallback": "gemini-2.5-flash",
            },
        },
        "deprecated": {
            "gemini-1.5-pro": {
                "replacement": "gemini-2.5-pro",
                "deadline": (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "reason": "EOL",
            },
        },
    }

    # _load_config をパッチして config を直接注入
    with patch.object(ModelRegistry, "_load_config", lambda self: setattr(self, '_config', config)):
        registry = ModelRegistry()

    yield registry

    # テスト後にシングルトンをリセット
    ModelRegistry._instance = None


# ============================================================
# ModelRegistry テスト
# ============================================================

class TestModelRegistry:
    """ModelRegistry: モデル選択・廃止警告・プラグイン登録"""

    def test_get_model_for_task_known(self, fresh_registry):
        """get_model_for_task: 既知のタスク"""
        # model_governanceはメソッド内でインポートされるため、importを失敗させる
        with patch.dict("sys.modules", {"model_governance": None}):
            model = fresh_registry.get_model_for_task("subtitle_split")
        assert model == "gemini-2.5-flash"

    def test_get_model_for_task_unknown_returns_default(self, fresh_registry):
        """get_model_for_task: 未知のタスク → デフォルト"""
        with patch.dict("sys.modules", {"model_governance": None}):
            model = fresh_registry.get_model_for_task("unknown_task")
        assert model == "gemini-2.5-flash"

    def test_get_model_for_deprecated_task(self, fresh_registry):
        """get_model_for_task: 廃止モデル → 代替モデル"""
        # task_mappingに廃止モデルを設定
        fresh_registry._config["task_mapping"]["legacy_task"] = "gemini-1.5-pro"
        with patch.dict("sys.modules", {"model_governance": None}):
            model = fresh_registry.get_model_for_task("legacy_task")
        assert model == "gemini-2.5-pro"  # replacement

    def test_get_default_model(self, fresh_registry):
        """get_default_model: デフォルトモデル"""
        assert fresh_registry.get_default_model() == "gemini-2.5-flash"

    def test_get_fallback_existing(self, fresh_registry):
        """get_fallback: 既存モデル"""
        fb = fresh_registry.get_fallback("gemini-2.5-pro")
        assert fb == "gemini-2.5-flash"

    def test_get_fallback_unknown(self, fresh_registry):
        """get_fallback: 未知のモデル → デフォルト"""
        fb = fresh_registry.get_fallback("nonexistent-model")
        assert fb == "gemini-2.5-flash"

    def test_check_deprecation_warnings(self, fresh_registry):
        """check_deprecation_warnings: 期限内の警告"""
        warnings = fresh_registry.check_deprecation_warnings()
        assert len(warnings) == 1
        assert warnings[0].model == "gemini-1.5-pro"
        assert warnings[0].replacement == "gemini-2.5-pro"
        assert warnings[0].days_remaining <= 90

    def test_validate_configuration_no_issues(self, fresh_registry):
        """validate_configuration: 問題なし"""
        issues = fresh_registry.validate_configuration()
        assert len(issues) == 0

    def test_validate_configuration_unknown_model(self, fresh_registry):
        """validate_configuration: 未知のモデル参照"""
        fresh_registry._config["task_mapping"]["bad_task"] = "nonexistent-model"
        issues = fresh_registry.validate_configuration()
        assert any("bad_task" in issue for issue in issues)

    def test_validate_configuration_invalid_fallback(self, fresh_registry):
        """validate_configuration: 無効なフォールバック"""
        fresh_registry._config["models"]["gemini-2.5-pro"]["fallback"] = "nonexistent"
        issues = fresh_registry.validate_configuration()
        assert any("invalid fallback" in issue for issue in issues)

    def test_register_plugin_requirement(self, fresh_registry):
        """register_plugin_requirement: プラグインモデル登録"""
        plugin = MagicMock()
        plugin.name = "test_plugin"
        plugin.model_requirements = {
            "task": "plugin_task",
            "model": "gemini-2.5-flash",
            "fallback": None,
        }
        fresh_registry.register_plugin_requirement(plugin)
        assert "plugin_task" in fresh_registry._config["task_mapping"]
        assert fresh_registry._config["task_mapping"]["plugin_task"] == "gemini-2.5-flash"

    def test_register_plugin_no_requirements(self, fresh_registry):
        """register_plugin_requirement: 要件なし → スキップ"""
        plugin = MagicMock()
        plugin.model_requirements = None
        fresh_registry.register_plugin_requirement(plugin)
        # エラーなし

    def test_run_startup_checks(self, fresh_registry):
        """run_startup_checks: 起動時チェック"""
        result = fresh_registry.run_startup_checks()
        assert "status" in result
        assert result["status"] in ("ok", "warning")
        assert "deprecation_warnings" in result

    def test_build_availability_dict_no_cache(self, fresh_registry):
        """_build_availability_dict: キャッシュなし → 空dict"""
        fresh_registry._available_models_cache = None
        result = fresh_registry._build_availability_dict()
        assert result == {}

    def test_build_availability_dict_with_cache(self, fresh_registry):
        """_build_availability_dict: キャッシュあり"""
        fresh_registry._available_models_cache = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]
        result = fresh_registry._build_availability_dict()
        assert result.get("gemini-2.5-flash") is True
        assert result.get("gemini-2.5-pro") is True

    def test_load_config_success(self):
        """_load_config: 正常にファイルを読み込む"""
        from model_registry import ModelRegistry
        import builtins
        from unittest.mock import mock_open
        
        ModelRegistry._instance = None
        mock_data = '{"version": "1.0.0-test", "default_model": "gemini-2.5-flash", "task_mapping": {}, "deprecated": {}}'
        
        with patch("builtins.open", mock_open(read_data=mock_data)):
            registry = ModelRegistry()
            assert registry._config["version"] == "1.0.0-test"
        
        ModelRegistry._instance = None

    def test_load_config_filenotfound(self):
        """_load_config: ファイルが存在しない場合"""
        from model_registry import ModelRegistry
        import builtins
        
        ModelRegistry._instance = None
        
        with patch("builtins.open", side_effect=FileNotFoundError):
            registry = ModelRegistry()
            assert registry._config["default_model"] == "gemini-2.5-flash"
            assert registry._config["task_mapping"] == {}
            
        ModelRegistry._instance = None

    def test_get_model_for_task_with_governance(self, fresh_registry):
        """get_model_for_task: model_governance が存在する場合"""
        mock_governance = MagicMock()
        mock_governance._resolve_model.return_value = "governed-model"
        
        with patch.dict("sys.modules", {"model_governance": mock_governance}):
            import sys
            mock_module = MagicMock()
            mock_module.model_governance = mock_governance
            sys.modules["model_governance"] = mock_module
            
            model = fresh_registry.get_model_for_task("subtitle_split")
            assert model == "governed-model"
            mock_governance._resolve_model.assert_called_once_with("subtitle_split")
            
        # クリーンアップ
        sys.modules.pop("model_governance", None)

    def test_check_model_availability_cache_valid(self, fresh_registry):
        """check_model_availability: キャッシュが有効期限内の場合"""
        from datetime import datetime
        fresh_registry._available_models_cache = ["gemini-2.5-flash"]
        fresh_registry._cache_timestamp = datetime.now()
        
        with patch("gemini_client_factory.get_gemini_client") as mock_get_client:
            res = fresh_registry.check_model_availability(force_refresh=False)
            mock_get_client.assert_not_called()
            assert res.get("gemini-2.5-flash") is True

    def test_check_model_availability_no_client(self, fresh_registry):
        """check_model_availability: クライアント取得不可"""
        fresh_registry._available_models_cache = None
        
        with patch("gemini_client_factory.get_gemini_client", return_value=None):
            res = fresh_registry.check_model_availability(force_refresh=True)
            assert res == {}

    def test_check_model_availability_api_error(self, fresh_registry):
        """check_model_availability: APIエラー発生時"""
        fresh_registry._available_models_cache = None
        mock_client = MagicMock()
        mock_client.models.list.side_effect = Exception("API error")
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = fresh_registry.check_model_availability(force_refresh=True)
            assert res == {}

    def test_check_model_availability_google_api_error(self, fresh_registry):
        """check_model_availability: Google API Error 発生時"""
        import google.api_core.exceptions
        fresh_registry._available_models_cache = None
        mock_client = MagicMock()
        mock_client.models.list.side_effect = google.api_core.exceptions.GoogleAPIError("API error")
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = fresh_registry.check_model_availability(force_refresh=True)
            assert res == {}

    def test_check_model_availability_import_error(self, fresh_registry):
        """check_model_availability: ImportError 発生時"""
        fresh_registry._available_models_cache = None
        mock_client = MagicMock()
        mock_client.models.list.side_effect = ImportError("Import error")
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = fresh_registry.check_model_availability(force_refresh=True)
            assert res == {}

    def test_check_model_availability_success(self, fresh_registry):
        """check_model_availability: APIから正常に取得"""
        fresh_registry._available_models_cache = None
        mock_client = MagicMock()
        
        mock_model = MagicMock()
        mock_model.name = "models/gemini-2.5-flash"
        mock_client.models.list.return_value = [mock_model]
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = fresh_registry.check_model_availability(force_refresh=True)
            assert res.get("gemini-2.5-flash") is True
            assert res.get("gemini-2.5-pro") is False

    def test_get_optimal_model_report(self, fresh_registry):
        """get_optimal_model_report: レポート生成の確認"""
        with patch.object(fresh_registry, "check_model_availability", return_value={"gemini-2.5-flash": True}):
            report = fresh_registry.get_optimal_model_report()
            assert "Model Registry - 最適性レポート" in report
            assert "subtitle_split" in report
            assert "gemini-2.5-flash" in report

    def test_register_plugin_no_model(self, fresh_registry):
        """register_plugin_requirement: model 要件がない場合は早期リターン"""
        plugin = MagicMock()
        plugin.model_requirements = {
            "task": "plugin_task"
        }
        original_config = fresh_registry._config.copy()
        fresh_registry.register_plugin_requirement(plugin)
        assert fresh_registry._config == original_config

    def test_register_plugin_missing_keys(self, fresh_registry):
        """register_plugin_requirement: task_mapping や models キーが config にない場合"""
        fresh_registry._config = {}
        
        plugin = MagicMock()
        plugin.name = "new_plugin"
        plugin.model_requirements = {
            "task": "plugin_task",
            "model": "new-model",
            "fallback": "gemini-2.5-flash"
        }
        
        fresh_registry.register_plugin_requirement(plugin)
        assert fresh_registry._config["task_mapping"]["plugin_task"] == "new-model"
        assert fresh_registry._config["models"]["new-model"]["fallback"] == "gemini-2.5-flash"
        assert "plugin_task" in fresh_registry._config["models"]["new-model"]["use_cases"]

    def test_register_plugin_existing_model_use_case(self, fresh_registry):
        """register_plugin_requirement: 既存のモデルに対して、別タスクのユースケースとして追加されるか"""
        plugin = MagicMock()
        plugin.name = "another_plugin"
        plugin.model_requirements = {
            "task": "another_task",
            "model": "gemini-2.5-flash",
            "fallback": None
        }
        
        fresh_registry.register_plugin_requirement(plugin)
        use_cases = fresh_registry._config["models"]["gemini-2.5-flash"]["use_cases"]
        assert "another_task" in use_cases

    def test_register_plugin_deprecated_warning(self, fresh_registry, caplog):
        """register_plugin_requirement: 廃止予定モデルを要求した場合の警告"""
        import logging
        plugin = MagicMock()
        plugin.name = "deprecated_plugin"
        plugin.model_requirements = {
            "task": "dep_task",
            "model": "gemini-1.5-pro",
            "fallback": None
        }
        
        with caplog.at_level(logging.WARNING):
            fresh_registry.register_plugin_requirement(plugin)
            assert any("uses deprecated model" in record.message for record in caplog.records)

    def test_run_startup_checks_with_issues(self, fresh_registry):
        """run_startup_checks: 設定不整合がある場合"""
        fresh_registry._config["task_mapping"]["bad_task"] = "nonexistent-model"
        
        result = fresh_registry.run_startup_checks()
        assert result["status"] == "warning"
        assert len(result["configuration_issues"]) > 0

    def test_global_functions(self):
        """ショートカットグローバル関数のテスト"""
        from model_registry import get_registry, get_model, run_startup_checks
        import model_registry
        
        model_registry.ModelRegistry._instance = None
        
        mock_data = '{"version": "test", "default_model": "gemini-2.5-flash", "task_mapping": {"task1": "gemini-2.5-flash"}, "models": {"gemini-2.5-flash": {}}, "deprecated": {}}'
        with patch("builtins.open", mock_open(read_data=mock_data)):
            reg = get_registry()
            assert isinstance(reg, model_registry.ModelRegistry)
            
            with patch.dict("sys.modules", {"model_governance": None}):
                assert get_model("task1") == "gemini-2.5-flash"
            
            checks = run_startup_checks()
            assert checks["status"] == "ok"

    def test_main_block(self):
        """__main__ ブロックのテスト"""
        import runpy
        import model_registry
        
        # 1. issuesがあるケース
        mock_data_issues = '{"version": "test", "default_model": "gemini-2.5-flash", "task_mapping": {"task1": "nonexistent-model"}, "models": {}, "deprecated": {}}'
        
        with patch("builtins.open", mock_open(read_data=mock_data_issues)):
            with patch("builtins.print") as mock_print:
                with patch.dict("sys.modules", {"model_governance": None}):
                    model_registry.ModelRegistry._instance = None
                    runpy.run_module("model_registry", run_name="__main__")
                    
                    printed_texts = [call[0][0] for call in mock_print.call_args_list if call[0]]
                    assert any("Model Registry - 最適性レポート" in text for text in printed_texts)
                    assert any("\n❌ 設定の問題点:" in text for text in printed_texts)
                    assert any("Task 'task1' references unknown model" in text for text in printed_texts)

        # 2. issuesがないケース
        mock_data_no_issues = '{"version": "test", "default_model": "gemini-2.5-flash", "task_mapping": {"task1": "gemini-2.5-flash"}, "models": {"gemini-2.5-flash": {}}, "deprecated": {}}'
        
        with patch("builtins.open", mock_open(read_data=mock_data_no_issues)):
            with patch("builtins.print") as mock_print:
                with patch.dict("sys.modules", {"model_governance": None}):
                    model_registry.ModelRegistry._instance = None
                    runpy.run_module("model_registry", run_name="__main__")
                    
                    printed_texts = [call[0][0] for call in mock_print.call_args_list if call[0]]
                    assert any("Model Registry - 最適性レポート" in text for text in printed_texts)
                    assert any("\n✅ 設定に問題はありません" in text for text in printed_texts)

    def test_is_cache_valid_no_timestamp(self, fresh_registry):
        """_is_cache_valid: キャッシュはあるがタイムスタンプがない場合"""
        fresh_registry._available_models_cache = ["gemini-2.5-flash"]
        fresh_registry._cache_timestamp = None
        assert fresh_registry._is_cache_valid(force_refresh=False) is False

    def test_module_level_model_config(self):
        """__getattr__ / __dir__: モジュールレベル의 MODEL_CONFIG"""
        import model_registry
        
        # 1. __getattr__ を経由して取得できること
        config = model_registry.MODEL_CONFIG
        assert isinstance(config, dict)
        
        # 2. 存在しない属性に対する AttributeError の確認
        with pytest.raises(AttributeError):
            _ = model_registry.NONEXISTENT_ATTRIBUTE
            
        # 3. __dir__ に MODEL_CONFIG が含まれること
        assert "MODEL_CONFIG" in dir(model_registry)
