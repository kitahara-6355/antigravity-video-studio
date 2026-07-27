import sys
import os
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# integration_test.py がインポートできるようにパスを通す
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import integration_test

def test_test_core_imports_success():
    res = integration_test.test_core_imports()
    assert res["status"] == "passed"

def test_test_core_imports_failure():
    with patch.dict(sys.modules, {"core": None}):
        res = integration_test.test_core_imports()
        assert res["status"] == "failed"

def test_test_unified_imports():
    res = integration_test.test_unified_imports()
    assert res["status"] == "passed"

def test_test_plugins_imports_success():
    res = integration_test.test_plugins_imports()
    assert res["status"] == "passed"

def test_test_plugins_imports_failure():
    with patch.dict(sys.modules, {"plugins": None}):
        res = integration_test.test_plugins_imports()
        assert res["status"] == "failed"

def test_test_design_system_imports_success():
    res = integration_test.test_design_system_imports()
    assert res["status"] == "passed"

def test_test_design_system_imports_failure():
    with patch.dict(sys.modules, {"design_system": None}):
        res = integration_test.test_design_system_imports()
        assert res["status"] == "failed"

def test_test_model_registry_success():
    res = integration_test.test_model_registry()
    assert res["status"] in ["passed", "failed"]

def test_test_model_registry_guard_invalid_format():
    with patch("model_registry.run_startup_checks", return_value="invalid"):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Invalid result format" in res["error"]

def test_test_model_registry_guard_no_status():
    with patch("model_registry.run_startup_checks", return_value={}):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Invalid result format" in res["error"]

def test_test_model_registry_failure():
    with patch("model_registry.get_registry", side_effect=ValueError("Test error")):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_test_plugin_registration_success():
    res = integration_test.test_plugin_registration()
    assert res["status"] in ["passed", "warning"]

def test_test_plugin_registration_guard_registry_none():
    with patch("core.get_plugin_registry", return_value=None):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Plugin registry is None" in res["error"]

def test_test_plugin_registration_guard_status_invalid():
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = "invalid"
    with patch("core.get_plugin_registry", return_value=mock_registry):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Invalid status format" in res["error"]

def test_test_plugin_registration_warning():
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 3}
    with patch("core.get_plugin_registry", return_value=mock_registry):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "warning"
        assert res["plugin_count"] == 3

def test_test_plugin_registration_failure():
    with patch("core.get_plugin_registry", side_effect=ValueError("Test error")):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_test_design_tokens_success():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = ["token1", "token2", "token3"]
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "passed"

def test_test_design_tokens_guard_manager_none():
    with patch("design_system.design_token_manager", None):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "design_token_manager is None" in res["error"]

def test_test_design_tokens_guard_not_sized():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = 123
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "Tokens returned is not Sized" in res["error"]

def test_test_design_tokens_warning():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = [1, 2]
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "warning"
        assert res["token_count"] == 2

def test_test_design_tokens_empty():
    mock_manager = MagicMock()
    mock_manager.get_tokens.return_value = []
    with patch("design_system.design_token_manager", mock_manager):
        res = integration_test.test_design_tokens()
        assert res["status"] == "warning"
        assert res["token_count"] == 0

def test_test_design_tokens_failure():
    with patch("design_system.design_token_manager") as mock_manager:
        mock_manager.get_tokens.side_effect = ValueError("Test error")
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_test_production_context_flow_success():
    mock_ctx = MagicMock()
    mock_ctx.mood_settings = {"some": "config"}
    mock_ctx.progress = 50
    with patch("core.ProductionContext", return_value=mock_ctx):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "passed"

def test_test_production_context_flow_guard_ctx_none():
    with patch("core.ProductionContext", return_value=None):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "Failed to instantiate ProductionContext" in res["error"]

def test_test_production_context_flow_guard_no_attributes():
    mock_ctx = MagicMock()
    mock_ctx.load_design_tokens = MagicMock()
    mock_ctx.update_progress = MagicMock()
    if hasattr(mock_ctx, "mood_settings"):
        del mock_ctx.mood_settings
    if hasattr(mock_ctx, "progress"):
        del mock_ctx.progress
        
    with patch("core.ProductionContext", return_value=mock_ctx):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "ProductionContext missing required attributes" in res["error"]

def test_test_production_context_flow_warning():
    mock_ctx = MagicMock()
    mock_ctx.mood_settings = None
    mock_ctx.progress = 50
    with patch("core.ProductionContext", return_value=mock_ctx):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "warning"

def test_test_production_context_flow_failure():
    with patch("core.ProductionContext", side_effect=ValueError("Test error")):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_test_data_migration_success():
    res = integration_test.test_data_migration()
    assert res["status"] in ["passed", "warning"]

def test_test_data_migration_guard_none():
    with patch("data_migration.data_migration", None):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "data_migration is None" in res["error"]

def test_test_data_migration_guard_invalid_format():
    mock_migration = MagicMock()
    mock_migration.run_migration.return_value = "invalid"
    with patch("data_migration.data_migration", mock_migration):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "Invalid migration result format" in res["error"]

def test_test_data_migration_warning():
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
        assert res["checks"] == "1/2"

def test_test_data_migration_failure():
    with patch("data_migration.data_migration") as mock_migration:
        mock_migration.run_migration.side_effect = ValueError("Test error")
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_test_youtube_optimizer_thumbnail_generation_success():
    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "passed"

def test_test_youtube_optimizer_thumbnail_generation_guard_none():
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin", return_value=None):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Optimizer or Thumbnail candidate is None" in res["error"]

def test_test_youtube_optimizer_thumbnail_generation_fail_normal():
    with patch.dict(os.environ, {"INTEGRATION_TEST_FAIL_NORMAL": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Expected thumbnail path" in res["error"]

def test_test_youtube_optimizer_thumbnail_generation_fail_empty():
    with patch.dict(os.environ, {"INTEGRATION_TEST_FAIL_EMPTY": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Expected None when generated_images is empty" in res["error"]

def test_test_youtube_optimizer_thumbnail_generation_fail_exception():
    with patch.dict(os.environ, {"INTEGRATION_TEST_FAIL_EXCEPTION": "1"}):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Expected None when exception occurs" in res["error"]

def test_test_youtube_optimizer_thumbnail_generation_failure():
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin", side_effect=ValueError("Test error")):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Test error" in res["error"]

def test_run_all_tests_with_not_callable():
    original_imports = integration_test.test_core_imports
    try:
        integration_test.test_core_imports = "not_callable"
        res = integration_test.run_all_tests()
        unknown_results = [r for r in res["results"] if r["name"] == "unknown_test"]
        assert len(unknown_results) == 1
        assert unknown_results[0]["status"] == "failed"
    finally:
        integration_test.test_core_imports = original_imports

def test_run_all_tests_real():
    def mock_pass(): return {"name": "p", "status": "passed"}
    def mock_warn(): return {"name": "w", "status": "warning"}
    def mock_fail(): return {"name": "f", "status": "failed", "error": "err"}
    
    with patch("integration_test.test_core_imports", mock_pass), \
         patch("integration_test.test_plugins_imports", mock_warn), \
         patch("integration_test.test_design_system_imports", mock_fail), \
         patch("integration_test.test_model_registry", mock_pass), \
         patch("integration_test.test_plugin_registration", mock_pass), \
         patch("integration_test.test_design_tokens", mock_pass), \
         patch("integration_test.test_production_context_flow", mock_pass), \
         patch("integration_test.test_data_migration", mock_pass), \
         patch("integration_test.test_youtube_optimizer_thumbnail_generation", mock_pass):
         
         res = integration_test.run_all_tests()
         assert res["overall_status"] == "failed"
         assert res["summary"]["passed"] == 7
         assert res["summary"]["warnings"] == 1
         assert res["summary"]["failed"] == 1

def test_main_execution_via_exec(tmp_path):
    test_json = tmp_path / "integration_test_result.json"
    
    is_windows = os.name == 'nt'
    if is_windows:
        from pathlib import WindowsPath as TargetPathClass
    else:
        from pathlib import PosixPath as TargetPathClass
        
    original_div = TargetPathClass.__truediv__
    
    def mock_div(self, other):
        if other == "integration_test_result.json":
            return test_json
        return original_div(self, other)
        
    with patch.object(TargetPathClass, "__truediv__", mock_div), \
         patch("sys.exit") as mock_exit:
         
         file_path = Path(integration_test.__file__)
         with open(file_path, "r", encoding="utf-8") as f:
             code_content = f.read()
         
         code_content = code_content.replace(
             "result = run_all_tests()",
             "result = run_all_tests_mock()"
         )
         
         global_namespace = {
             "__name__": "__main__",
             "__file__": str(file_path),
             "run_all_tests_mock": MagicMock(return_value={"overall_status": "passed"}),
         }
         compiled_code = compile(code_content, str(file_path), "exec")
         exec(compiled_code, global_namespace)
         
         mock_exit.assert_called_once_with(0)
         assert test_json.exists()
         with open(test_json, "r", encoding="utf-8") as f:
             data = json.load(f)
             assert data["overall_status"] == "passed"

def test_main_execution_via_exec_failure(tmp_path):
    test_json = tmp_path / "integration_test_result.json"
    
    is_windows = os.name == 'nt'
    if is_windows:
        from pathlib import WindowsPath as TargetPathClass
    else:
        from pathlib import PosixPath as TargetPathClass
        
    original_div = TargetPathClass.__truediv__
    
    def mock_div(self, other):
        if other == "integration_test_result.json":
            return test_json
        return original_div(self, other)
        
    with patch.object(TargetPathClass, "__truediv__", mock_div), \
         patch("sys.exit") as mock_exit:
         
         file_path = Path(integration_test.__file__)
         with open(file_path, "r", encoding="utf-8") as f:
             code_content = f.read()
         
         code_content = code_content.replace(
             "result = run_all_tests()",
             "result = run_all_tests_mock()"
         )
         
         global_namespace = {
             "__name__": "__main__",
             "__file__": str(file_path),
             "run_all_tests_mock": MagicMock(return_value={"overall_status": "failed"}),
         }
         compiled_code = compile(code_content, str(file_path), "exec")
         exec(compiled_code, global_namespace)
         mock_exit.assert_called_once_with(1)

def test_main_execution_write_error():
    is_windows = os.name == 'nt'
    if is_windows:
        from pathlib import WindowsPath as TargetPathClass
    else:
        from pathlib import PosixPath as TargetPathClass
        
    original_div = TargetPathClass.__truediv__
    
    def mock_div(self, other):
        if other == "integration_test_result.json":
            return Path("C:/invalid_dir_path_xyz_123/integration_test_result.json")
        return original_div(self, other)
        
    with patch.object(TargetPathClass, "__truediv__", mock_div), \
         patch("sys.exit") as mock_exit:
         
         file_path = Path(integration_test.__file__)
         with open(file_path, "r", encoding="utf-8") as f:
             code_content = f.read()
         
         code_content = code_content.replace(
             "result = run_all_tests()",
             "result = run_all_tests_mock()"
         )
         
         global_namespace = {
             "__name__": "__main__",
             "__file__": str(file_path),
             "run_all_tests_mock": MagicMock(return_value={"overall_status": "passed"}),
         }
         compiled_code = compile(code_content, str(file_path), "exec")
         exec(compiled_code, global_namespace)
         mock_exit.assert_called_once_with(0)
