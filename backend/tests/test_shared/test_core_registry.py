"""
core.registry.py に対するユニットテスト
"""
import sys
import pytest
from unittest.mock import patch, MagicMock

from core.plugin import Plugin, PluginPhase
from core.context import ProductionContext
from core.registry import PluginRegistry, get_plugin_registry, register_plugin

class DummyPlugin(Plugin):
    def __init__(self, name="dummy", phase=PluginPhase.GENERATION, priority=50, model_req=None):
        self._name = name
        self._phase = phase
        self._priority = priority
        self._model_req = model_req
        self.executed = False
        self.can_execute_val = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def phase(self) -> PluginPhase:
        return self._phase

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def model_requirements(self):
        return self._model_req

    def can_execute(self, context: ProductionContext) -> bool:
        return self.can_execute_val

    def execute(self, context: ProductionContext) -> ProductionContext:
        self.executed = True
        context.set_extension(f"{self.name}_executed", True)
        return context

class ErrorPlugin(DummyPlugin):
    def execute(self, context: ProductionContext) -> ProductionContext:
        raise ValueError("Simulated execution failure")

class TestCoreRegistry:
    def test_init(self):
        registry = PluginRegistry()
        assert len(registry.list_plugins()) == 0
        assert len(registry.get_model_requirements()) == 0

    def test_register_and_get(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1")
        registry.register(p1)
        
        assert registry.get("p1") == p1
        assert registry.list_plugins() == [p1]

        # 重複登録時の警告ログ
        p1_dup = DummyPlugin("p1")
        with patch('core.registry.logger') as mock_logger:
            registry.register(p1_dup)
            mock_logger.warning.assert_called_with("Plugin p1 already registered, overwriting")
            assert registry.get("p1") == p1_dup

    def test_unregister(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1")
        registry.register(p1)
        
        unregistered = registry.unregister("p1")
        assert unregistered == p1
        assert registry.get("p1") is None
        
        # 存在しないもののアンレジスター
        assert registry.unregister("nonexistent") is None

    def test_collect_model_requirements_empty(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req=None)
        registry.register(p1)
        assert len(registry.get_model_requirements()) == 0

    def test_collect_model_requirements_no_model(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"task": "t1"}) # modelがない
        registry.register(p1)
        assert len(registry.get_model_requirements()) == 0

    def test_collect_model_requirements_success(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"task": "t1", "model": "gemini-pro", "fallback": "gemini-flash", "api_type": "gemini"})
        
        with patch('model_registry.get_registry') as mock_get_reg:
            mock_reg_inst = MagicMock()
            mock_get_reg.return_value = mock_reg_inst
            
            registry.register(p1)
            
            mock_reg_inst.register_plugin_requirement.assert_called_with(p1)
            
            reqs = registry.get_model_requirements()
            assert "t1" in reqs
            assert reqs["t1"]["model"] == "gemini-pro"
            assert reqs["t1"]["fallback"] == "gemini-flash"
            assert reqs["t1"]["api_type"] == "gemini"
            assert reqs["t1"]["plugin"] == "p1"

    def test_collect_model_requirements_default_task_name(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"}) # task省略
        
        with patch('model_registry.get_registry') as mock_get_reg:
            mock_reg_inst = MagicMock()
            mock_get_reg.return_value = mock_reg_inst
            
            registry.register(p1)
            
            reqs = registry.get_model_requirements()
            # taskがない場合は plugin.name がキーになる
            assert "p1" in reqs
            assert reqs["p1"]["model"] == "gemini-pro"
            assert reqs["p1"]["api_type"] == "gemini" # デフォルト値

    def test_collect_model_requirements_import_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        # model_registry のインポートを失敗させる
        old_mr = sys.modules.get('model_registry')
        sys.modules['model_registry'] = None
        try:
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.warning.call_count == 1
                assert "ModelRegistry not available for model registration" in mock_logger.warning.call_args[0][0]
        finally:
            if old_mr is not None:
                sys.modules['model_registry'] = old_mr
            else:
                sys.modules.pop('model_registry', None)

    def test_collect_model_requirements_value_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        with patch('model_registry.get_registry', side_effect=ValueError("Invalid configuration")):
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.warning.call_count == 1
                assert "Invalid model requirement configuration in plugin" in mock_logger.warning.call_args[0][0]

    def test_collect_model_requirements_unexpected_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        with patch('model_registry.get_registry', side_effect=RuntimeError("Unexpected DB connection failure")):
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.exception.call_count == 1
                assert "Unexpected error registering model requirement for plugin" in mock_logger.exception.call_args[0][0]

    def test_get_plugins_by_phase(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", phase=PluginPhase.ANALYSIS, priority=30)
        p2 = DummyPlugin("p2", phase=PluginPhase.ANALYSIS, priority=10)
        p3 = DummyPlugin("p3", phase=PluginPhase.GENERATION, priority=50)
        
        registry.register(p1)
        registry.register(p2)
        registry.register(p3)
        
        # 優先度の低い（数値が小さい）順にソートされる
        analysis_plugins = registry.get_plugins_by_phase(PluginPhase.ANALYSIS)
        assert analysis_plugins == [p2, p1]

    def test_execute_phase(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", phase=PluginPhase.GENERATION, priority=50)
        p2 = DummyPlugin("p2", phase=PluginPhase.GENERATION, priority=30)
        
        # 実行不可プラグイン
        p3 = DummyPlugin("p3", phase=PluginPhase.GENERATION, priority=10)
        p3.can_execute_val = False
        
        registry.register(p1)
        registry.register(p2)
        registry.register(p3)
        
        context = ProductionContext(task_id="test_task")
        updated_context = registry.execute_phase(PluginPhase.GENERATION, context)
        
        assert p2.executed is True
        assert p1.executed is True
        assert p3.executed is False
        assert updated_context.get_extension("p1_executed") is True
        assert updated_context.get_extension("p2_executed") is True
        assert updated_context.get_extension("p3_executed") is None

    def test_execute_phase_with_error(self):
        registry = PluginRegistry()
        p1 = ErrorPlugin("err_plugin", phase=PluginPhase.GENERATION)
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with patch('core.registry.logger') as mock_logger:
            updated_context = registry.execute_phase(PluginPhase.GENERATION, context)
            
            # exceptionがログに記録されていること
            assert mock_logger.exception.call_count == 1
            assert "failed with exception" in mock_logger.exception.call_args[0][0]
            # on_error が実行されて context にエラー情報が記録されていること
            assert updated_context.get_extension("err_plugin_error") == "Simulated execution failure"

    def test_execute_all(self):
        registry = PluginRegistry()
        p_pre = DummyPlugin("p_pre", phase=PluginPhase.PRE_PROCESS)
        p_ana = DummyPlugin("p_ana", phase=PluginPhase.ANALYSIS)
        p_gen = DummyPlugin("p_gen", phase=PluginPhase.GENERATION)
        p_post = DummyPlugin("p_post", phase=PluginPhase.POST_PROCESS)
        p_fin = DummyPlugin("p_fin", phase=PluginPhase.FINALIZATION)
        
        registry.register(p_pre)
        registry.register(p_ana)
        registry.register(p_gen)
        registry.register(p_post)
        registry.register(p_fin)
        
        context = ProductionContext(task_id="test_task")
        updated_context = registry.execute_all(context)
        
        assert p_pre.executed is True
        assert p_ana.executed is True
        assert p_gen.executed is True
        assert p_post.executed is True
        assert p_fin.executed is True

    def test_get_status(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", phase=PluginPhase.ANALYSIS, priority=30)
        p2 = DummyPlugin("p2", phase=PluginPhase.GENERATION, priority=50)
        registry.register(p1)
        registry.register(p2)
        
        status = registry.get_status()
        assert status["total_plugins"] == 2
        assert status["model_requirements"] == 0
        assert len(status["plugins_by_phase"]["analysis"]) == 1
        assert status["plugins_by_phase"]["analysis"][0]["name"] == "p1"
        assert status["plugins_by_phase"]["analysis"][0]["priority"] == 30

    def test_global_registry_functions(self):
        # グローバル変数 _registry のリセットをシミュレート
        import core.registry
        core.registry._registry = None
        
        # 1回目の取得で初期化されること
        reg1 = get_plugin_registry()
        assert isinstance(reg1, PluginRegistry)
        
        # 2回目は同じインスタンスが返ること
        reg2 = get_plugin_registry()
        assert reg1 is reg2
        
        # register_plugin のショートカットが動作すること
        p1 = DummyPlugin("p_global")
        register_plugin(p1)
        assert reg1.get("p_global") is p1

    def test_collect_model_requirements_attribute_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        with patch('model_registry.get_registry', side_effect=AttributeError("Simulated AttributeError")):
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.warning.call_count == 1
                assert "Invalid model requirement configuration in plugin" in mock_logger.warning.call_args[0][0]

    def test_collect_model_requirements_type_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        with patch('model_registry.get_registry', side_effect=TypeError("Simulated TypeError")):
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.warning.call_count == 1
                assert "Invalid model requirement configuration in plugin" in mock_logger.warning.call_args[0][0]

    def test_execute_all_phase_transitions(self):
        class PhaseTrackingPlugin(DummyPlugin):
            def __init__(self, name, phase):
                super().__init__(name, phase)
                self.executed_phase = None
            def execute(self, context: ProductionContext) -> ProductionContext:
                self.executed = True
                self.executed_phase = context.phase
                return context

        registry = PluginRegistry()
        p_pre = PhaseTrackingPlugin("p_pre", PluginPhase.PRE_PROCESS)
        p_ana = PhaseTrackingPlugin("p_ana", PluginPhase.ANALYSIS)
        p_gen = PhaseTrackingPlugin("p_gen", PluginPhase.GENERATION)
        p_post = PhaseTrackingPlugin("p_post", PluginPhase.POST_PROCESS)
        p_fin = PhaseTrackingPlugin("p_fin", PluginPhase.FINALIZATION)
        
        registry.register(p_pre)
        registry.register(p_ana)
        registry.register(p_gen)
        registry.register(p_post)
        registry.register(p_fin)
        
        context = ProductionContext(task_id="test_task")
        updated_context = registry.execute_all(context)
        
        from core.context import ProductionPhase
        assert p_pre.executed_phase == ProductionPhase.PRE_PROCESS
        assert p_ana.executed_phase == ProductionPhase.ANALYSIS
        assert p_gen.executed_phase == ProductionPhase.GENERATION
        assert p_post.executed_phase == ProductionPhase.POST_PROCESS
        assert p_fin.executed_phase == ProductionPhase.FINALIZATION

    def test_execute_phase_skip_log(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", phase=PluginPhase.GENERATION)
        p1.can_execute_val = False
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with patch('core.registry.logger') as mock_logger:
            registry.execute_phase(PluginPhase.GENERATION, context)
            assert mock_logger.info.call_count >= 1
            # "Skipping plugin p1 (can_execute=False)" がログに記録されていること
            skip_log_found = any("Skipping plugin p1" in call[0][0] for call in mock_logger.info.call_args_list)
            assert skip_log_found is True

    def test_execute_phase_plugin_returns_none(self):
        class NonePlugin(DummyPlugin):
            def execute(self, context: ProductionContext) -> ProductionContext:
                self.executed = True
                return None  # Noneを返す

        registry = PluginRegistry()
        p1 = NonePlugin("none_plugin", phase=PluginPhase.GENERATION)
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with patch('core.registry.logger') as mock_logger:
            updated_context = registry.execute_phase(PluginPhase.GENERATION, context)
            
            assert p1.executed is True
            # 元の context が破壊されずに返されていること
            assert updated_context is context
            # 警告ログが出力されていること
            warning_log_found = any("returned None context" in call[0][0] for call in mock_logger.warning.call_args_list)
            assert warning_log_found is True

    def test_execute_phase_on_error_returns_none(self):
        class BadErrorPlugin(DummyPlugin):
            def execute(self, context: ProductionContext) -> ProductionContext:
                raise ValueError("Simulated execution failure")
            def on_error(self, context: ProductionContext, error: Exception) -> ProductionContext:
                return None  # on_errorがNoneを返す

        registry = PluginRegistry()
        p1 = BadErrorPlugin("bad_plugin", phase=PluginPhase.GENERATION)
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with patch('core.registry.logger') as mock_logger:
            updated_context = registry.execute_phase(PluginPhase.GENERATION, context)
            
            # 元の context が返っていること
            assert updated_context is context
            # エラー情報が extensions に設定されていること
            assert updated_context.get_extension("bad_plugin_error") == "Simulated execution failure"
            # 警告ログが出力されていること
            warning_log_found = any("on_error() returned None context" in call[0][0] for call in mock_logger.warning.call_args_list)
            assert warning_log_found is True

    def test_execute_phase_on_error_raises_exception(self):
        class DoubleErrorPlugin(DummyPlugin):
            def execute(self, context: ProductionContext) -> ProductionContext:
                raise ValueError("First error")
            def on_error(self, context: ProductionContext, error: Exception) -> ProductionContext:
                raise RuntimeError("Second error in on_error")

        registry = PluginRegistry()
        p1 = DoubleErrorPlugin("double_err_plugin", phase=PluginPhase.GENERATION)
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with patch('core.registry.logger') as mock_logger:
            # 例外が外に漏れずに正常に処理が終わること
            updated_context = registry.execute_phase(PluginPhase.GENERATION, context)
            
            # 元の context が返っていること
            assert updated_context is context
            # エラー情報が extensions に設定され、両方のエラーメッセージが含まれていること
            error_msg = updated_context.get_extension("double_err_plugin_error")
            assert "First error" in error_msg
            assert "Second error" in error_msg
            # logger.errorが呼ばれていること
            assert mock_logger.error.call_count == 1
            assert "on_error call failed" in mock_logger.error.call_args[0][0]

    def test_collect_model_requirements_key_error(self):
        registry = PluginRegistry()
        p1 = DummyPlugin("p1", model_req={"model": "gemini-pro"})
        
        with patch('model_registry.get_registry', side_effect=KeyError("Simulated KeyError")):
            with patch('core.registry.logger') as mock_logger:
                registry.register(p1)
                assert mock_logger.exception.call_count == 1
                assert "Unexpected error registering model requirement for plugin" in mock_logger.exception.call_args[0][0]

    def test_execute_phase_raises_base_exception(self):
        class SystemExitPlugin(DummyPlugin):
            def execute(self, context: ProductionContext) -> ProductionContext:
                raise SystemExit("Fatal exit")

        registry = PluginRegistry()
        p1 = SystemExitPlugin("exit_plugin", phase=PluginPhase.GENERATION)
        registry.register(p1)
        
        context = ProductionContext(task_id="test_task")
        with pytest.raises(SystemExit):
            registry.execute_phase(PluginPhase.GENERATION, context)

    def test_validation_failures(self):
        registry = PluginRegistry()
        
        # register(None) のバリデーションテスト
        with pytest.raises(TypeError, match="Plugin cannot be None"):
            registry.register(None)
            
        # get のバリデーションテスト
        with pytest.raises(TypeError, match="Plugin name must be a string"):
            registry.get(None)
        with pytest.raises(ValueError, match="Plugin name cannot be empty"):
            registry.get("")
            
        # unregister のバリデーションテスト
        with pytest.raises(TypeError, match="Plugin name must be a string"):
            registry.unregister(None)
        with pytest.raises(ValueError, match="Plugin name cannot be empty"):
            registry.unregister("")


