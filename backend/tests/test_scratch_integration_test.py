import sys
import os
import pytest
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend パスを追加
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import integration_test

def test_integration_test_functions_normal():
    # 各関数の正常系テスト
    res = integration_test.test_core_imports()
    assert res["status"] in ("passed", "failed")

    res = integration_test.test_unified_imports()
    assert res["status"] == "passed"

    res = integration_test.test_plugins_imports()
    assert res["status"] in ("passed", "failed")

    res = integration_test.test_design_system_imports()
    assert res["status"] in ("passed", "failed")

    res = integration_test.test_model_registry()
    assert res["status"] in ("passed", "failed")

    res = integration_test.test_plugin_registration()
    assert res["status"] in ("passed", "warning", "failed")

    res = integration_test.test_design_tokens()
    assert res["status"] in ("passed", "warning", "failed")

    res = integration_test.test_production_context_flow()
    assert res["status"] in ("passed", "warning", "failed")

    res = integration_test.test_data_migration()
    assert res["status"] in ("passed", "warning", "failed")

    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] in ("passed", "failed")

def test_design_tokens_passed():
    # design_tokens が正常系（passed）になるモックテスト
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = ["a", "b", "c"]
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "passed"

def test_production_context_flow_passed():
    # production_context_flow が正常系（passed）になるモックテスト
    class MockPassedContext:
        def __init__(self, *args, **kwargs):
            self.progress = 0
            self.mood_settings = None
        def load_design_tokens(self):
            self.mood_settings = {"loaded": True}
        def update_progress(self, progress, desc):
            self.progress = progress

    with patch("core.ProductionContext", MockPassedContext), \
         patch("design_system.DesignSystemPlugin"):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "passed"

def test_imports_failures():
    # test_core_imports の例外系
    with patch.dict("sys.modules", {"core": None}):
        res = integration_test.test_core_imports()
        assert res["status"] == "failed"

    # test_plugins_imports の例外系
    with patch.dict("sys.modules", {"plugins": None}):
        res = integration_test.test_plugins_imports()
        assert res["status"] == "failed"

    # test_design_system_imports の例外系
    with patch.dict("sys.modules", {"design_system": None}):
        res = integration_test.test_design_system_imports()
        assert res["status"] == "failed"

def test_model_registry_variations():
    # test_model_registry の例外系
    with patch.dict("sys.modules", {"model_registry": None}):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"

    # run_startup_checks が ok/warning 以外を返すケース (failed 分岐)
    mock_registry = MagicMock()
    with patch("model_registry.get_registry", return_value=mock_registry), \
         patch("model_registry.run_startup_checks", return_value={"status": "error"}):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"

def test_plugin_registration_variations():
    # test_plugin_registration の例外系
    with patch.dict("sys.modules", {"plugins": None}):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"

    # total_plugins が 5 未満の警告ケース
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 4}
    with patch("core.get_plugin_registry", return_value=mock_registry), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "warning"
        assert res["plugin_count"] == 4

def test_design_tokens_variations():
    # test_design_tokens の例外系
    with patch.dict("sys.modules", {"design_system": None}):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"

    # tokens が 3 未満の警告ケース
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = ["one", "two"] # 長さ 2
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "warning"

    # tokens が None の失敗ケース（Sizedではないためfailedになるのが正しい挙動）
    mock_manager_none = MagicMock()
    mock_manager_none.get_tokens.return_value = None
    with patch("design_system.design_token_manager", mock_manager_none):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"

def test_production_context_flow_variations():
    # test_production_context_flow の例外系
    with patch.dict("sys.modules", {"core": None}):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"

    # 条件が満たされない警告ケース
    # progress が 50 ではない、または mood_settings が False
    class MockContext:
        def __init__(self, *args, **kwargs):
            self.progress = 40  # 50 以外にする
            self.mood_settings = None
        def load_design_tokens(self):
            pass
        def update_progress(self, progress, desc):
            pass

    with patch("core.ProductionContext", MockContext), \
         patch("design_system.DesignSystemPlugin"):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "warning"

def test_data_migration_variations():
    # test_data_migration の例外系
    with patch.dict("sys.modules", {"data_migration": None}):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"

    # ステップの一部が passed ではない警告ケース
    mock_migration = MagicMock()
    mock_migration.run_migration.return_value = {
        "steps": [
            {"status": "passed"},
            {"status": "failed"}
        ]
    }
    with patch("data_migration.data_migration", mock_migration):
        res = integration_test.test_data_migration()
        assert res["status"] == "warning"

def test_youtube_optimizer_variations():
    # 環境変数での AssertionError 分岐
    # 1. INTEGRATION_TEST_FAIL_NORMAL = 1
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_NORMAL": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

    # 2. INTEGRATION_TEST_FAIL_EMPTY = 1
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_EMPTY": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

    # 3. INTEGRATION_TEST_FAIL_EXCEPTION = 1
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_EXCEPTION": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

    # インポート失敗による例外系
    with patch.dict("sys.modules", {"plugins.youtube_optimizer_plugin": None}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

def test_run_all_tests_and_main():
    # run_all_tests を個別に呼び出し、各 status 分岐（passed, warning, failed）と overall_status をテストする。
    mocks = {
        "test_core_imports": lambda: {"name": "core", "status": "passed"},
        "test_plugins_imports": lambda: {"name": "plugins", "status": "warning"},
        "test_design_system_imports": lambda: {"name": "design", "status": "failed", "error": "err"},
        "test_model_registry": lambda: {"name": "model", "status": "passed"},
        "test_plugin_registration": lambda: {"name": "reg", "status": "passed"},
        "test_design_tokens": lambda: {"name": "tokens", "status": "passed"},
        "test_production_context_flow": lambda: {"name": "ctx", "status": "passed"},
        "test_data_migration": lambda: {"name": "mig", "status": "passed"},
        "test_youtube_optimizer_thumbnail_generation": lambda: {"name": "yt", "status": "passed"},
    }
    
    with patch.multiple(integration_test, **mocks):
        res = integration_test.run_all_tests()
        assert res["overall_status"] == "failed"
        assert res["summary"]["failed"] == 1
        assert res["summary"]["warnings"] == 1

    # failed が 0 のケース
    mocks_all_passed = {k: (lambda k=k: {"name": k, "status": "passed"}) for k in mocks}
    with patch.multiple(integration_test, **mocks_all_passed):
        res = integration_test.run_all_tests()
        assert res["overall_status"] == "passed"
        assert res["summary"]["failed"] == 0

def test_main_block():
    # __name__ == "__main__" ブロックの実行
    output_file = backend_dir / "integration_test_result.json"
    
    # 正常系 (overall_status == "passed") のテスト
    with patch("sys.exit") as mock_exit:
        runpy.run_path(str(backend_dir / "integration_test.py"), run_name="__main__")
        mock_exit.assert_called_with(0)

    if output_file.exists():
        output_file.unlink()

    # 異常系 (overall_status == "failed") のテスト
    # 環境変数 INTEGRATION_TEST_FAIL_NORMAL を指定して、実際のテストのうち1つを失敗させる
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_NORMAL": "1"}), \
         patch("sys.exit") as mock_exit_failed:
         
        runpy.run_path(str(backend_dir / "integration_test.py"), run_name="__main__")
        mock_exit_failed.assert_called_with(1)

    if output_file.exists():
        output_file.unlink()

def test_integration_test_extra_coverage():
    # 1. test_model_registry 内のガード処理 (73, 79)
    # 73: registry is None
    with patch("model_registry.get_registry", return_value=None):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "ModelRegistry is None" in res["error"]

    # 79: Invalid result format from run_startup_checks (status が辞書ではない、または status が辞書にない)
    # result is not dict
    with patch("model_registry.get_registry", return_value=MagicMock()), \
         patch("model_registry.run_startup_checks", return_value="not_a_dict"):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Invalid result format" in res["error"]

    # result has no status
    with patch("model_registry.get_registry", return_value=MagicMock()), \
         patch("model_registry.run_startup_checks", return_value={"no_status": 1}):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Invalid result format" in res["error"]

    # 2. test_plugin_registration 内のガード処理 (105, 111)
    # 105: registry is None
    with patch("core.get_plugin_registry", return_value=None), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Plugin registry is None" in res["error"]

    # 111: Invalid status format (not dict)
    mock_reg = MagicMock()
    mock_reg.get_status.return_value = "not_a_dict"
    with patch("core.get_plugin_registry", return_value=mock_reg), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Invalid status format" in res["error"]

    # 3. test_design_tokens 内のガード処理 (140)
    # 140: design_token_manager is None
    with patch("design_system.design_token_manager", None):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "design_token_manager is None" in res["error"]

    # 4. test_production_context_flow 内のガード処理 (179, 189, 196)
    # 179: ctx is None
    with patch("core.ProductionContext", return_value=None):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "Failed to instantiate ProductionContext" in res["error"]

    # 189: ctx missing required attributes
    class BadContext1:
        def __init__(self, *args, **kwargs):
            pass
        def load_design_tokens(self):
            pass
        def update_progress(self, progress, desc):
            pass
    with patch("core.ProductionContext", BadContext1), \
         patch("design_system.DesignSystemPlugin"):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "missing required attributes" in res["error"]

    # 196: ctx.mood_settings is not None and not isinstance(ctx.mood_settings, dict)
    class BadContext2:
        def __init__(self, *args, **kwargs):
            self.progress = 50
            self.mood_settings = "not_a_dict"
        def load_design_tokens(self):
            pass
        def update_progress(self, progress, desc):
            pass
    with patch("core.ProductionContext", BadContext2), \
         patch("design_system.DesignSystemPlugin"):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "Invalid mood_settings format" in res["error"]

    # 5. test_data_migration 内のガード処理 (224, 230, 238)
    # 224: data_migration is None
    with patch("data_migration.data_migration", None):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "data_migration is None" in res["error"]

    # 230: Invalid migration result format (not dict, steps not in result, steps not list)
    mock_mig = MagicMock()
    mock_mig.run_migration.return_value = "not_a_dict"
    with patch("data_migration.data_migration", mock_mig):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "Invalid migration result format" in res["error"]

    # 238: Invalid step format in steps (step is not dict, status not in step)
    mock_mig = MagicMock()
    mock_mig.run_migration.return_value = {
        "steps": ["not_a_dict_step"]
    }
    with patch("data_migration.data_migration", mock_mig):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "Invalid step format" in res["error"]

    # 6. test_youtube_optimizer_thumbnail_generation 内のガード処理 (274)
    # 274: optimizer is None or thumbnail is None
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin", return_value=None):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Optimizer or Thumbnail candidate is None" in res["error"]

    # 7. run_all_tests 内の呼び出し可能判定 (348-349)
    # 348-349: not callable(test_func)
    with patch("integration_test.test_core_imports", "not_callable"):
        res = integration_test.run_all_tests()
        assert res["overall_status"] == "failed"
        unknown_results = [r for r in res["results"] if r["name"] == "unknown_test"]
        assert len(unknown_results) > 0
        assert unknown_results[0]["status"] == "failed"

    # 8. main 内の保存失敗例外処理 (398-399)
    # OSError or IOError
    # file open/write error simulation
    with patch("builtins.open", side_effect=OSError("Disk Full")), \
         patch("sys.exit") as mock_exit:
        integration_test.main()
        mock_exit.assert_called_with(0)

def test_strict_assertions_for_imports():
    # 1. test_core_imports 正常系モック
    mock_core = MagicMock()
    with patch.dict("sys.modules", {"core": mock_core}):
        res = integration_test.test_core_imports()
        assert res == {"name": "core_imports", "status": "passed"}

    # 2. test_plugins_imports 正常系モック
    mock_plugins = MagicMock()
    with patch.dict("sys.modules", {"plugins": mock_plugins}):
        res = integration_test.test_plugins_imports()
        assert res == {"name": "plugins_imports", "status": "passed"}

    # 3. test_design_system_imports 正常系モック
    mock_ds = MagicMock()
    with patch.dict("sys.modules", {"design_system": mock_ds}):
        res = integration_test.test_design_system_imports()
        assert res == {"name": "design_system_imports", "status": "passed"}

def test_strict_assertions_for_model_registry():
    # test_model_registry の正常系（ok / warning / failed）の詳細な値検証
    mock_registry = MagicMock()
    
    # ok の場合
    with patch("model_registry.get_registry", return_value=mock_registry), \
         patch("model_registry.run_startup_checks", return_value={"status": "ok"}):
        res = integration_test.test_model_registry()
        assert res == {
            "name": "model_registry",
            "status": "passed",
            "startup_result": "ok"
        }

    # warning の場合
    with patch("model_registry.get_registry", return_value=mock_registry), \
         patch("model_registry.run_startup_checks", return_value={"status": "warning"}):
        res = integration_test.test_model_registry()
        assert res == {
            "name": "model_registry",
            "status": "passed",
            "startup_result": "warning"
        }

    # その他のステータスの場合（failedになる）
    with patch("model_registry.get_registry", return_value=mock_registry), \
         patch("model_registry.run_startup_checks", return_value={"status": "unexpected"}):
        res = integration_test.test_model_registry()
        assert res == {
            "name": "model_registry",
            "status": "failed",
            "startup_result": "unexpected"
        }

def test_strict_assertions_for_plugin_registration():
    # total_plugins >= 5 (passed)
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 6}
    with patch("core.get_plugin_registry", return_value=mock_registry), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res == {
            "name": "plugin_registration",
            "status": "passed",
            "plugin_count": 6
        }

    # total_plugins < 5 (warning)
    mock_registry.get_status.return_value = {"total_plugins": 3}
    with patch("core.get_plugin_registry", return_value=mock_registry), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res == {
            "name": "plugin_registration",
            "status": "warning",
            "plugin_count": 3,
            "expected": 5
        }

def test_strict_assertions_for_data_migration():
    # 全ステップが passed の場合 (passed)
    mock_migration = MagicMock()
    mock_migration.run_migration.return_value = {
        "steps": [
            {"status": "passed"},
            {"status": "passed"},
            {"status": "passed"}
        ]
    }
    with patch("data_migration.data_migration", mock_migration):
        res = integration_test.test_data_migration()
        assert res == {
            "name": "data_migration",
            "status": "passed",
            "checks": "3/3"
        }

    # ステップの一部が passed ではない場合 (warning)
    mock_migration.run_migration.return_value = {
        "steps": [
            {"status": "passed"},
            {"status": "failed"}
        ]
    }
    with patch("data_migration.data_migration", mock_migration):
        res = integration_test.test_data_migration()
        assert res == {
            "name": "data_migration",
            "status": "warning",
            "checks": "1/2"
        }
