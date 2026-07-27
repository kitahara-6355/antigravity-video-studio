"""
core.plugin.py に対するユニットテスト
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from core.plugin import Plugin, PluginPhase
from core.context import ProductionContext

class DummyPlugin(Plugin):
    @property
    def name(self) -> str:
        return "dummy_plugin"

    def execute(self, context: ProductionContext) -> ProductionContext:
        context.set_extension("dummy_executed", True)
        return context

class DummyPluginWithReq(Plugin):
    @property
    def name(self) -> str:
        return "dummy_with_req"

    @property
    def model_requirements(self):
        return {
            "task": "test_task",
            "model": "gemini-test-default",
            "fallback": "gemini-test-fallback"
        }

    def execute(self, context: ProductionContext) -> ProductionContext:
        return context

class TestCorePlugin:
    def test_plugin_phase_values(self):
        assert PluginPhase.PRE_PROCESS.value == "pre_process"
        assert PluginPhase.ANALYSIS.value == "analysis"
        assert PluginPhase.GENERATION.value == "generation"
        assert PluginPhase.POST_PROCESS.value == "post_process"
        assert PluginPhase.FINALIZATION.value == "finalization"

    def test_plugin_defaults(self):
        plugin = DummyPlugin()
        assert plugin.name == "dummy_plugin"
        assert plugin.phase == PluginPhase.GENERATION
        assert plugin.priority == 50
        assert plugin.model_requirements is None
        assert plugin.get_model() is None
        context = ProductionContext(task_id="test")
        assert plugin.can_execute(context) is True
        assert repr(plugin) == "<Plugin dummy_plugin phase=generation priority=50>"

    def test_plugin_on_error(self):
        plugin = DummyPlugin()
        context = ProductionContext(task_id="test")
        error = ValueError("Something went wrong")
        
        with patch('core.plugin.logger') as mock_logger:
            new_context = plugin.on_error(context, error)
            mock_logger.error.assert_called_with("Plugin dummy_plugin error: Something went wrong")
            assert new_context.get_extension("dummy_plugin_error") == "Something went wrong"

    def test_plugin_log(self):
        plugin = DummyPlugin()
        with patch('core.plugin.logger') as mock_logger:
            plugin.log("Hello info")
            mock_logger.info.assert_called_with("[dummy_plugin] Hello info")

            plugin.log("Hello warning", level="warning")
            mock_logger.warning.assert_called_with("[dummy_plugin] Hello warning")

    def test_get_model_normal(self):
        plugin = DummyPluginWithReq()
        with patch('backend.model_registry.get_model', return_value="gemini-test-resolved") as mock_get_model:
            model = plugin.get_model()
            assert model == "gemini-test-resolved"
            mock_get_model.assert_called_with("test_task")

    def test_get_model_fallback_import(self):
        plugin = DummyPluginWithReq()
        
        # backend.model_registry を sys.modules から一時的に None にして ImportError をシミュレート
        old_backend_mr = sys.modules.get('backend.model_registry')
        sys.modules['backend.model_registry'] = None
        
        try:
            with patch('model_registry.get_model', return_value="gemini-fallback-resolved") as mock_get_model:
                model = plugin.get_model()
                assert model == "gemini-fallback-resolved"
                mock_get_model.assert_called_with("test_task")
        finally:
            if old_backend_mr is not None:
                sys.modules['backend.model_registry'] = old_backend_mr
            else:
                sys.modules.pop('backend.model_registry', None)

    def test_get_model_import_error(self):
        plugin = DummyPluginWithReq()
        
        # 両方のインポートを失敗させる
        old_backend_mr = sys.modules.get('backend.model_registry')
        old_mr = sys.modules.get('model_registry')
        
        sys.modules['backend.model_registry'] = None
        sys.modules['model_registry'] = None
        
        try:
            with patch('core.plugin.logger') as mock_logger:
                model = plugin.get_model()
                assert model == "gemini-test-default"
                assert mock_logger.warning.call_count == 1
                log_msg = mock_logger.warning.call_args[0][0]
                assert "ModelRegistry not available, using declared model" in log_msg
        finally:
            if old_backend_mr is not None:
                sys.modules['backend.model_registry'] = old_backend_mr
            else:
                sys.modules.pop('backend.model_registry', None)
                
            if old_mr is not None:
                sys.modules['model_registry'] = old_mr
            else:
                sys.modules.pop('model_registry', None)

    def test_get_model_other_exceptions(self):
        plugin = DummyPluginWithReq()
        
        # get_model 呼び出し時に ValueError を発生させる
        with patch('backend.model_registry.get_model', side_effect=ValueError("Invalid configuration")):
            with patch('core.plugin.logger') as mock_logger:
                model = plugin.get_model()
                assert model == "gemini-test-default"
                assert mock_logger.warning.call_count == 1
                log_msg = mock_logger.warning.call_args[0][0]
                assert "ModelRegistry not available, using declared model" in log_msg

    def test_abstract_base_calls(self):
        plugin = DummyPlugin()
        context = ProductionContext(task_id="test")
        
        # Plugin.name の fget (pass) を呼び出す
        res_name = Plugin.name.fget(plugin)
        assert res_name is None
        
        # Plugin.execute (pass) を呼び出す
        res_exec = Plugin.execute(plugin, context)
        assert res_exec is None
