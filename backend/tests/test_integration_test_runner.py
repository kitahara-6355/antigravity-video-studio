import sys
import builtins
import json
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# テスト対象がインポートできるように PYTHONPATH に backend を追加
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import integration_test


def test_core_imports_success():
    # 正常系インポート
    res = integration_test.test_core_imports()
    assert res["status"] == "passed"


def test_core_imports_failure():
    # 異常系インポート（builtins.__import__ をパッチ）
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "core" or name.startswith("core."):
            raise ImportError("Mocked core import failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        res = integration_test.test_core_imports()
        assert res["status"] == "failed"
        assert "Mocked core import failure" in res["error"]


def test_unified_imports():
    res = integration_test.test_unified_imports()
    assert res["status"] == "passed"
    assert "archived" in res["note"]


def test_plugins_imports_success():
    res = integration_test.test_plugins_imports()
    assert res["status"] == "passed"


def test_plugins_imports_failure():
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "plugins" or name.startswith("plugins."):
            raise ImportError("Mocked plugins import failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        res = integration_test.test_plugins_imports()
        assert res["status"] == "failed"
        assert "Mocked plugins import failure" in res["error"]


def test_design_system_imports_success():
    res = integration_test.test_design_system_imports()
    assert res["status"] == "passed"


def test_design_system_imports_failure():
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "design_system" or name.startswith("design_system."):
            raise ImportError("Mocked design_system import failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        res = integration_test.test_design_system_imports()
        assert res["status"] == "failed"
        assert "Mocked design_system import failure" in res["error"]


def test_model_registry_success():
    # 正常系 (run_startup_checks が ok または warning)
    with patch("model_registry.run_startup_checks", return_value={"status": "ok"}):
        res = integration_test.test_model_registry()
        assert res["status"] == "passed"
        assert res["startup_result"] == "ok"

    with patch("model_registry.run_startup_checks", return_value={"status": "warning"}):
        res = integration_test.test_model_registry()
        assert res["status"] == "passed"
        assert res["startup_result"] == "warning"


def test_model_registry_failed_status():
    # スタートアップチェックが ok/warning 以外
    with patch("model_registry.run_startup_checks", return_value={"status": "failed_check"}):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert res["startup_result"] == "failed_check"


def test_model_registry_exception():
    # 例外ルート (インポートまたは処理中にエラー)
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "model_registry" or name.startswith("model_registry."):
            raise ImportError("Mocked model_registry import failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        res = integration_test.test_model_registry()
        assert res["status"] == "failed"
        assert "Mocked model_registry import failure" in res["error"]


def test_plugin_registration_success():
    # プラグイン数 >= 5
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 6}
    with patch("core.get_plugin_registry", return_value=mock_registry), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "passed"
        assert res["plugin_count"] == 6


def test_plugin_registration_warning():
    # プラグイン数 < 5
    mock_registry = MagicMock()
    mock_registry.get_status.return_value = {"total_plugins": 3}
    with patch("core.get_plugin_registry", return_value=mock_registry), \
         patch("plugins.register_all_plugins"):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "warning"
        assert res["plugin_count"] == 3


def test_plugin_registration_exception():
    # 例外ルート
    with patch("core.get_plugin_registry", side_effect=Exception("Plugin registration crashed")):
        res = integration_test.test_plugin_registration()
        assert res["status"] == "failed"
        assert "Plugin registration crashed" in res["error"]


def test_design_tokens_success():
    # トークン数 >= 3
    mock_tokens = {"color1": "#fff", "color2": "#000", "color3": "#ccc"}
    with patch("design_system.design_token_manager.DesignTokenManager.get_tokens", return_value=mock_tokens):
        res = integration_test.test_design_tokens()
        assert res["status"] == "passed"
        assert res["token_count"] == 3


def test_design_tokens_warning():
    # トークン数 < 3 または None
    with patch("design_system.design_token_manager.DesignTokenManager.get_tokens", return_value={"color1": "#fff"}):
        res = integration_test.test_design_tokens()
        assert res["status"] == "warning"
        assert res["token_count"] == 1

    with patch("design_system.design_token_manager.DesignTokenManager.get_tokens", return_value=None):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "Tokens returned is not Sized" in res["error"]

    with patch("design_system.design_token_manager.DesignTokenManager.get_tokens", return_value=[]):
        res = integration_test.test_design_tokens()
        assert res["status"] == "warning"
        assert res["token_count"] == 0


def test_design_tokens_exception():
    # 例外ルート
    with patch("design_system.design_token_manager.DesignTokenManager.get_tokens", side_effect=Exception("Token manager error")):
        res = integration_test.test_design_tokens()
        assert res["status"] == "failed"
        assert "Token manager error" in res["error"]


def test_production_context_flow_success():
    # mood_settings があり progress == 50
    with patch("core.ProductionContext") as MockCtx:
        mock_instance = MockCtx.return_value
        mock_instance.mood_settings = {"theme": "elegant"}
        mock_instance.progress = 50
        
        res = integration_test.test_production_context_flow()
        assert res["status"] == "passed"
        assert res["mood_settings_loaded"] is True


def test_production_context_flow_warning():
    # mood_settings が空、または progress != 50
    with patch("core.ProductionContext") as MockCtx:
        mock_instance = MockCtx.return_value
        mock_instance.mood_settings = {}
        mock_instance.progress = 50
        
        res = integration_test.test_production_context_flow()
        assert res["status"] == "warning"
        assert res["mood_settings_loaded"] is False


def test_production_context_flow_exception():
    # 例外ルート
    with patch("core.ProductionContext", side_effect=Exception("ProductionContext instantiation failed")):
        res = integration_test.test_production_context_flow()
        assert res["status"] == "failed"
        assert "ProductionContext instantiation failed" in res["error"]


def test_data_migration_success():
    # 全ステップ passed
    mock_result = {
        "steps": [
            {"name": "step1", "status": "passed"},
            {"name": "step2", "status": "passed"}
        ]
    }
    with patch("data_migration.data_migration.run_migration", return_value=mock_result):
        res = integration_test.test_data_migration()
        assert res["status"] == "passed"
        assert res["checks"] == "2/2"


def test_data_migration_warning():
    # 一部ステップが非 passed
    mock_result = {
        "steps": [
            {"name": "step1", "status": "passed"},
            {"name": "step2", "status": "warning"}
        ]
    }
    with patch("data_migration.data_migration.run_migration", return_value=mock_result):
        res = integration_test.test_data_migration()
        assert res["status"] == "warning"
        assert res["checks"] == "1/2"


def test_data_migration_exception():
    # 例外ルート
    with patch("data_migration.data_migration.run_migration", side_effect=Exception("Migration crashed")):
        res = integration_test.test_data_migration()
        assert res["status"] == "failed"
        assert "Migration crashed" in res["error"]


def test_run_all_tests_with_warning_and_failed():
    # run_all_tests内の status == 'warning' や status == 'failed' の時の print 分岐もカバーする
    mock_tests = [
        lambda: {"name": "mock_pass", "status": "passed"},
        lambda: {"name": "mock_warn", "status": "warning"},
        lambda: {"name": "mock_fail", "status": "failed", "error": "test failure error"}
    ]
    with patch("integration_test.test_core_imports", mock_tests[0]), \
         patch("integration_test.test_plugins_imports", mock_tests[1]), \
         patch("integration_test.test_design_system_imports", mock_tests[2]), \
         patch("integration_test.test_model_registry", mock_tests[0]), \
         patch("integration_test.test_plugin_registration", mock_tests[0]), \
         patch("integration_test.test_design_tokens", mock_tests[0]), \
         patch("integration_test.test_production_context_flow", mock_tests[0]), \
         patch("integration_test.test_data_migration", mock_tests[0]), \
         patch("integration_test.test_youtube_optimizer_thumbnail_generation", mock_tests[0]):
         
        res = integration_test.run_all_tests()
        assert res["overall_status"] == "failed"
        assert res["summary"]["passed"] == 7
        assert res["summary"]["warnings"] == 1
        assert res["summary"]["failed"] == 1


def test_main_block_success():
    # __main__ ブロックの正常系テスト。
    # 通常通り run_path を動かし、正常終了することを確認する。
    json_path = backend_dir / "integration_test_result.json"
    json_path.unlink(missing_ok=True)
    
    try:
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(backend_dir / "integration_test.py"), run_name="__main__")
        
        assert excinfo.value.code == 0
        assert json_path.exists()
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["overall_status"] == "passed"
    finally:
        json_path.unlink(missing_ok=True)


def test_main_block_failed():
    # __main__ ブロックの異常系テスト（テスト失敗による終了コード 1）。
    # builtins.__import__ をモックして core インポートを失敗させる。
    json_path = backend_dir / "integration_test_result.json"
    json_path.unlink(missing_ok=True)
    
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "core" or name.startswith("core."):
            raise ImportError("Mocked core import failure for main block test")
        return original_import(name, *args, **kwargs)

    try:
        with patch("builtins.__import__", side_effect=mock_import), \
             pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(backend_dir / "integration_test.py"), run_name="__main__")
            
        assert excinfo.value.code == 1
        assert json_path.exists()
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["overall_status"] == "failed"
    finally:
        json_path.unlink(missing_ok=True)


def test_youtube_optimizer_thumbnail_generation_runner_success():
    # integration_test.py 自体の test_youtube_optimizer_thumbnail_generation メソッドが成功するケース
    # すでにモックが含まれているため、正常に passed が返されることを検証
    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "passed"


def test_youtube_optimizer_thumbnail_generation_runner_exception():
    # インポート失敗などの例外発生時のルートをカバーする
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "plugins.youtube_optimizer_plugin" or name.startswith("plugins.youtube_optimizer_plugin."):
            raise ImportError("Mocked plugin import failure")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        res = integration_test.test_youtube_optimizer_thumbnail_generation()
        assert res["status"] == "failed"
        assert "Mocked plugin import failure" in res["error"]


def test_youtube_optimizer_thumbnail_generation_runner_failed_paths(monkeypatch):
    # integration_test.py の test_youtube_optimizer_thumbnail_generation 内の失敗分岐をカバーする
    
    # 1. 正常系でアサーションが失敗する場合
    monkeypatch.setenv("INTEGRATION_TEST_FAIL_NORMAL", "1")
    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "failed"
    assert "Expected thumbnail path" in res["error"]
    monkeypatch.delenv("INTEGRATION_TEST_FAIL_NORMAL", raising=False)
    
    # 2. 異常系1（空）でアサーションが失敗する場合
    monkeypatch.setenv("INTEGRATION_TEST_FAIL_EMPTY", "1")
    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "failed"
    assert "Expected None when generated_images is empty" in res["error"]
    monkeypatch.delenv("INTEGRATION_TEST_FAIL_EMPTY", raising=False)
    
    # 3. 異常系2（例外）でアサーションが失敗する場合
    monkeypatch.setenv("INTEGRATION_TEST_FAIL_EXCEPTION", "1")
    res = integration_test.test_youtube_optimizer_thumbnail_generation()
    assert res["status"] == "failed"
    assert "Expected None when exception occurs" in res["error"]
    monkeypatch.delenv("INTEGRATION_TEST_FAIL_EXCEPTION", raising=False)
