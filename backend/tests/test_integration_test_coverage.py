import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# ルートパスを追加
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.integration_test import (
    test_core_imports,
    test_unified_imports,
    test_plugins_imports,
    test_design_system_imports,
    test_model_registry,
    test_plugin_registration,
    test_design_tokens,
    test_production_context_flow,
    test_data_migration,
    test_youtube_optimizer_thumbnail_generation,
    run_all_tests,
    main
)

def test_core_imports_success():
    res = test_core_imports()
    assert res["status"] == "passed"

def test_core_imports_failure():
    # インポート時に例外を発生させる
    with patch.dict("sys.modules", {"core": None}):
        res = test_core_imports()
        assert res["status"] == "failed"
        assert "error" in res

def test_unified_imports_success():
    res = test_unified_imports()
    assert res["status"] == "passed"

def test_plugins_imports_success():
    res = test_plugins_imports()
    assert res["status"] == "passed"

def test_plugins_imports_failure():
    with patch.dict("sys.modules", {"plugins": None}):
        res = test_plugins_imports()
        assert res["status"] == "failed"

def test_design_system_imports_success():
    res = test_design_system_imports()
    assert res["status"] == "passed"

def test_design_system_imports_failure():
    with patch.dict("sys.modules", {"design_system": None}):
        res = test_design_system_imports()
        assert res["status"] == "failed"

def test_model_registry_success():
    res = test_model_registry()
    assert "status" in res

def test_model_registry_none():
    with patch("model_registry.get_registry", return_value=None):
        res = test_model_registry()
        assert res["status"] == "failed"
        assert "ModelRegistry is None" in res["error"]

def test_model_registry_invalid_format():
    with patch("model_registry.run_startup_checks", return_value="not_dict"):
        res = test_model_registry()
        assert res["status"] == "failed"
        assert "Invalid result format" in res["error"]

def test_model_registry_exception():
    with patch("model_registry.get_registry", side_effect=Exception("Registry error")):
        res = test_model_registry()
        assert res["status"] == "failed"
        assert "Registry error" in res["error"]

def test_plugin_registration_success():
    res = test_plugin_registration()
    assert "status" in res

def test_plugin_registration_none():
    with patch("core.get_plugin_registry", return_value=None):
        res = test_plugin_registration()
        assert res["status"] == "failed"
        assert "Plugin registry is None" in res["error"]

def test_plugin_registration_invalid_status():
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = "not_dict"
    with patch("core.get_plugin_registry", return_value=mock_registry):
        res = test_plugin_registration()
        assert res["status"] == "failed"
        assert "Invalid status format" in res["error"]

def test_plugin_registration_warning():
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 2}
    with patch("core.get_plugin_registry", return_value=mock_registry):
        res = test_plugin_registration()
        assert res["status"] == "warning"
        assert res["plugin_count"] == 2

def test_plugin_registration_exception():
    with patch("core.get_plugin_registry", side_effect=Exception("Registry fetch error")):
        res = test_plugin_registration()
        assert res["status"] == "failed"
        assert "Registry fetch error" in res["error"]

def test_design_tokens_success():
    res = test_design_tokens()
    assert "status" in res

def test_design_tokens_none():
    with patch("design_system.design_token_manager", None):
        res = test_design_tokens()
        assert res["status"] == "failed"
        assert "design_token_manager is None" in res["error"]

def test_design_tokens_not_sized():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = 123  # Not Sized
    with patch("design_system.design_token_manager", mock_manager):
        res = test_design_tokens()
        assert res["status"] == "failed"
        assert "is not Sized" in res["error"]

def test_design_tokens_warning():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = ["token1"]  # Sized but len < 3
    with patch("design_system.design_token_manager", mock_manager):
        res = test_design_tokens()
        assert res["status"] == "warning"
        assert res["token_count"] == 1

def test_design_tokens_exception():
    with patch("design_system.design_token_manager") as mock_manager:
        mock_manager.get_tokens.side_effect = Exception("Token error")
        res = test_design_tokens()
        assert res["status"] == "failed"
        assert "Token error" in res["error"]

def test_production_context_flow_success():
    res = test_production_context_flow()
    assert "status" in res

def test_production_context_flow_missing_attributes():
    class MockContext:
        def __init__(self, *args, **kwargs):
            self.progress = 50
        def load_design_tokens(self):
            pass
        def update_progress(self, *args):
            pass

    with patch("core.ProductionContext", MockContext):
        res = test_production_context_flow()
        assert res["status"] == "failed"
        assert "missing required attributes" in res["error"]

def test_production_context_flow_invalid_mood_settings():
    class MockContext:
        def __init__(self, *args, **kwargs):
            self.mood_settings = "not_dict"
            self.progress = 50
        def load_design_tokens(self):
            pass
        def update_progress(self, *args):
            pass

    with patch("core.ProductionContext", MockContext):
        res = test_production_context_flow()
        assert res["status"] == "failed"
        assert "Invalid mood_settings format" in res["error"]

def test_production_context_flow_warning():
    class MockContext:
        def __init__(self, *args, **kwargs):
            self.mood_settings = {}  # Empty
            self.progress = 50
        def load_design_tokens(self):
            pass
        def update_progress(self, *args):
            pass

    with patch("core.ProductionContext", MockContext):
        res = test_production_context_flow()
        assert res["status"] == "warning"
        assert res["mood_settings_loaded"] is False

def test_production_context_flow_exception():
    with patch("core.ProductionContext", side_effect=Exception("Context error")):
        res = test_production_context_flow()
        assert res["status"] == "failed"
        assert "Context error" in res["error"]

def test_data_migration_success():
    res = test_data_migration()
    assert "status" in res

def test_data_migration_none():
    with patch("data_migration.data_migration", None):
        res = test_data_migration()
        assert res["status"] == "failed"
        assert "data_migration is None" in res["error"]

def test_data_migration_invalid_result_format():
    mock_migration = MagicMock()
    mock_migration.run_migration.return_value = "not_dict"
    with patch("data_migration.data_migration", mock_migration):
        res = test_data_migration()
        assert res["status"] == "failed"
        assert "Invalid migration result format" in res["error"]

def test_data_migration_invalid_step_format():
    mock_migration = MagicMock()
    mock_migration.run_migration.return_value = {"steps": ["not_dict"]}
    with patch("data_migration.data_migration", mock_migration):
        res = test_data_migration()
        assert res["status"] == "failed"
        assert "Invalid step format" in res["error"]

def test_data_migration_exception():
    with patch("data_migration.data_migration") as mock_migration:
        mock_migration.run_migration.side_effect = Exception("Migration error")
        res = test_data_migration()
        assert res["status"] == "failed"
        assert "Migration error" in res["error"]

def test_youtube_optimizer_thumbnail_generation_success():
    res = test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "passed"

def test_youtube_optimizer_thumbnail_generation_fail_normal():
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_NORMAL": "1"}):
        res = test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

def test_youtube_optimizer_thumbnail_generation_fail_empty():
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_EMPTY": "1"}):
        res = test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

def test_youtube_optimizer_thumbnail_generation_fail_exception():
    with patch.dict("os.environ", {"INTEGRATION_TEST_FAIL_EXCEPTION": "1"}):
        res = test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"

def test_youtube_optimizer_thumbnail_generation_none():
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin", return_value=None):
        res = test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Optimizer or Thumbnail candidate is None" in res["error"]

def test_run_all_tests_success():
    res = run_all_tests()
    assert "overall_status" in res

def test_run_all_tests_not_callable():
    with patch("backend.integration_test.test_core_imports", "not_callable"):
        res = run_all_tests()
        assert any(r["name"] == "unknown_test" for r in res["results"])

def test_main_success(tmp_path):
    output_file = tmp_path / "integration_test_result.json"
    with patch("backend.integration_test.Path.parent", output_file.parent),          patch("sys.exit") as mock_exit:
        main()
        mock_exit.assert_called_once_with(0)
        assert output_file.exists()
        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["overall_status"] == "passed"

def test_main_file_write_error(tmp_path):
    with patch("builtins.open", side_effect=OSError("Disk full")),          patch("sys.exit") as mock_exit:
        main()
        mock_exit.assert_called_once()


def test_design_tokens_len_ge_3():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = ["t1", "t2", "t3"]
    with patch("design_system.design_token_manager", mock_manager):
        res = test_design_tokens()
        assert res["status"] == "passed"
        assert res["token_count"] == 3

def test_production_context_flow_ctx_none():
    with patch("core.ProductionContext", return_value=None):
        res = test_production_context_flow()
        assert res["status"] == "failed"
        assert "Failed to instantiate ProductionContext" in res["error"]

def test_production_context_flow_passed_status():
    mock_ctx = MagicMock()
    mock_ctx.mood_settings = {"primary": "#ffffff"}
    mock_ctx.progress = 50
    with patch("core.ProductionContext", return_value=mock_ctx):
        res = test_production_context_flow()
        assert res["status"] == "passed"
        assert res["mood_settings_loaded"] is True

def test_run_all_tests_failed_status():
    mock_test = MagicMock()
    mock_test.__name__ = "mock_test_imports"
    mock_test.return_value = {"name": "mock_test_imports", "status": "failed", "error": "Simulated error"}
    
    with patch("backend.integration_test.test_core_imports", mock_test):
        res = run_all_tests()
        assert res["overall_status"] == "failed"
        assert res["summary"]["failed"] > 0

def test_integration_test_direct_run():
    import runpy
    # sys.exit をモックすることで run_path 内の main() 実行によるプロセス終了を防ぐ
    with patch("sys.exit") as mock_exit:
        current_dir = Path(__file__).parent
        if current_dir.name == "tests":
            if current_dir.parent.name == "backend":
                project_root = current_dir.parent.parent
            else:
                project_root = current_dir.parent
        else:
            project_root = current_dir.parent.parent
        path = str(project_root / "backend" / "integration_test.py")
        runpy.run_path(path, run_name="__main__")
        mock_exit.assert_called_once()

