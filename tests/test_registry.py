import sys
import pytest
from unittest.mock import MagicMock, patch
import logging

from backend.core.plugin import Plugin, PluginPhase
from backend.core.context import ProductionContext, ProductionPhase
from backend.core.registry import (
    PluginRegistry,
    get_plugin_registry,
    register_plugin,
)

# ロガー設定
logger = logging.getLogger(__name__)

# テスト用ダミープラグインクラス
class DummyPlugin(Plugin):
    def __init__(self, name, phase=PluginPhase.GENERATION, priority=50, model_requirements=None, can_execute_val=True):
        self._name = name
        self._phase = phase
        self._priority = priority
        self._model_requirements = model_requirements
        self._can_execute = can_execute_val
        self.execute_called = False
        self.on_error_called = False
        self.error_passed = None

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
        return self._model_requirements

    def can_execute(self, context) -> bool:
        return self._can_execute

    def execute(self, context):
        self.execute_called = True
        if self._name == "error_plugin":
            raise RuntimeError("Dummy execution failure")
        context.set_extension(f"{self._name}_executed", True)
        return context

    def on_error(self, context, error):
        self.on_error_called = True
        self.error_passed = error
        return super().on_error(context, error)


def test_registry_initialization():
    """初期化の検証"""
    registry = PluginRegistry()
    assert registry.list_plugins() == []
    assert registry.get_model_requirements() == {}


def test_register_and_unregister():
    """プラグイン登録と解除、および上書き登録の警告検証"""
    registry = PluginRegistry()
    plugin1 = DummyPlugin("plugin1")
    
    # 登録
    registry.register(plugin1)
    assert registry.get("plugin1") == plugin1
    assert registry.list_plugins() == [plugin1]
    
    # 重複登録 (Warning ログが走る)
    plugin1_dup = DummyPlugin("plugin1", priority=60)
    with patch('backend.core.registry.logger.warning') as mock_warn:
        registry.register(plugin1_dup)
        assert registry.get("plugin1") == plugin1_dup
        mock_warn.assert_called_once()
        
    # 解除
    unregistered = registry.unregister("plugin1")
    assert unregistered == plugin1_dup
    assert registry.get("plugin1") is None
    
    # 存在しないプラグインの解除
    assert registry.unregister("non_existent") is None


def test_collect_model_requirements_scenarios():
    """モデル要件自動収集の様々なシナリオ検証"""
    
    # 1. model_requirements が None の場合
    registry = PluginRegistry()
    plugin_none = DummyPlugin("none_plugin", model_requirements=None)
    registry.register(plugin_none)
    assert "none_plugin" not in registry.get_model_requirements()

    # 2. model_requirements に model がない場合
    plugin_no_model = DummyPlugin("no_model_plugin", model_requirements={"task": "task1"})
    registry.register(plugin_no_model)
    assert "task1" not in registry.get_model_requirements()

    # 3. 正常系: model_registry が利用可能な場合
    mock_registry_instance = MagicMock()
    mock_model_registry = MagicMock()
    mock_model_registry.get_registry.return_value = mock_registry_instance
    
    plugin_ok = DummyPlugin(
        "ok_plugin",
        model_requirements={"task": "task_ok", "model": "gemini-test", "fallback": "gemini-fallback", "api_type": "gemini"}
    )
    
    with patch.dict(sys.modules, {"model_registry": mock_model_registry}):
        registry.register(plugin_ok)
        reqs = registry.get_model_requirements()
        assert "task_ok" in reqs
        assert reqs["task_ok"]["model"] == "gemini-test"
        assert reqs["task_ok"]["fallback"] == "gemini-fallback"
        assert reqs["task_ok"]["api_type"] == "gemini"
        assert reqs["task_ok"]["plugin"] == "ok_plugin"
        mock_model_registry.get_registry.assert_called_once()
        mock_registry_instance.register_plugin_requirement.assert_called_once_with(plugin_ok)

    # 4. model_registry インポート時に ImportError が発生する場合 (境界検証)
    plugin_import_err = DummyPlugin(
        "import_err_plugin",
        model_requirements={"task": "task_import_err", "model": "gemini-test"}
    )
    with patch.dict(sys.modules, {"model_registry": None}):
        with patch('backend.core.registry.logger.warning') as mock_warn:
            registry.register(plugin_import_err)
            assert "task_import_err" in registry.get_model_requirements()
            mock_warn.assert_any_call("ModelRegistry not available for model registration")

    # 5. model_registry 登録時に AttributeError/TypeError/ValueError が発生する場合 (境界検証)
    plugin_val_err = DummyPlugin(
        "val_err_plugin",
        model_requirements={"task": "task_val_err", "model": "gemini-test"}
    )
    mock_model_registry_err = MagicMock()
    mock_model_registry_err.get_registry.side_effect = ValueError("Invalid structure")
    with patch.dict(sys.modules, {"model_registry": mock_model_registry_err}):
        with patch('backend.core.registry.logger.warning') as mock_warn:
            registry.register(plugin_val_err)
            assert "task_val_err" in registry.get_model_requirements()
            assert any("Invalid model requirement configuration" in call[0][0] for call in mock_warn.call_args_list)

    # 6. model_registry 登録時に想定外の一般 Exception が発生する場合 (境界検証)
    plugin_runtime_err = DummyPlugin(
        "runtime_err_plugin",
        model_requirements={"task": "task_runtime_err", "model": "gemini-test"}
    )
    mock_model_registry_runtime = MagicMock()
    mock_model_registry_runtime.get_registry.side_effect = RuntimeError("Unexpected DB issue")
    with patch.dict(sys.modules, {"model_registry": mock_model_registry_runtime}):
        with patch('backend.core.registry.logger.exception') as mock_exc:
            registry.register(plugin_runtime_err)
            assert "task_runtime_err" in registry.get_model_requirements()
            assert any("Unexpected error registering model requirement" in call[0][0] for call in mock_exc.call_args_list)


def test_get_plugins_by_phase():
    """フェーズごとの優先度順ソート検証"""
    registry = PluginRegistry()
    p1 = DummyPlugin("p1", phase=PluginPhase.ANALYSIS, priority=100)
    p2 = DummyPlugin("p2", phase=PluginPhase.ANALYSIS, priority=10)
    p3 = DummyPlugin("p3", phase=PluginPhase.GENERATION, priority=50)
    
    registry.register(p1)
    registry.register(p2)
    registry.register(p3)
    
    analysis_plugins = registry.get_plugins_by_phase(PluginPhase.ANALYSIS)
    assert analysis_plugins == [p2, p1]


def test_execute_phase_and_error_handling():
    """フェーズ実行時の挙動、スキップ、および例外フォールバックの境界検証"""
    registry = PluginRegistry()
    context = ProductionContext()
    
    p_ok = DummyPlugin("ok_plugin", phase=PluginPhase.GENERATION)
    p_skip = DummyPlugin("skip_plugin", phase=PluginPhase.GENERATION, can_execute_val=False)
    p_err = DummyPlugin("error_plugin", phase=PluginPhase.GENERATION)
    
    registry.register(p_ok)
    registry.register(p_skip)
    registry.register(p_err)
    
    context = registry.execute_phase(PluginPhase.GENERATION, context)
    
    assert p_ok.execute_called is True
    assert context.get_extension("ok_plugin_executed") is True
    
    assert p_skip.execute_called is False
    assert context.get_extension("skip_plugin_executed") is None
    
    assert p_err.execute_called is True
    assert p_err.on_error_called is True
    assert isinstance(p_err.error_passed, RuntimeError)
    assert "Dummy execution failure" in context.get_extension("error_plugin_error")


def test_execute_all():
    """execute_all による全フェーズの順次実行の検証"""
    registry = PluginRegistry()
    context = ProductionContext()
    
    phases = [
        PluginPhase.PRE_PROCESS,
        PluginPhase.ANALYSIS,
        PluginPhase.GENERATION,
        PluginPhase.POST_PROCESS,
        PluginPhase.FINALIZATION
    ]
    
    plugins = []
    for i, phase in enumerate(phases):
        p = DummyPlugin(f"plugin_phase_{i}", phase=phase)
        registry.register(p)
        plugins.append(p)
        
    context = registry.execute_all(context)
    
    for p in plugins:
        assert p.execute_called is True
        
    assert context.phase.value == "finalization"


def test_get_status():
    """get_status 診断情報の検証"""
    registry = PluginRegistry()
    p1 = DummyPlugin("p1", phase=PluginPhase.ANALYSIS, priority=20)
    p2 = DummyPlugin("p2", phase=PluginPhase.GENERATION, priority=30, model_requirements={"task": "t2", "model": "m2"})
    
    registry.register(p1)
    registry.register(p2)
    
    status = registry.get_status()
    assert status["total_plugins"] == 2
    assert status["model_requirements"] == 1
    assert "analysis" in status["plugins_by_phase"]
    assert status["plugins_by_phase"]["analysis"] == [{"name": "p1", "priority": 20}]
    assert status["plugins_by_phase"]["generation"] == [{"name": "p2", "priority": 30}]


def test_global_registry_helpers():
    """グローバルレジストリヘルパー関数のシングルトン動作検証"""
    import backend.core.registry as reg_module
    
    orig_registry = reg_module._registry
    reg_module._registry = None
    
    try:
        r1 = get_plugin_registry()
        r2 = get_plugin_registry()
        assert r1 is r2
        
        plugin = DummyPlugin("global_plugin")
        register_plugin(plugin)
        assert r1.get("global_plugin") == plugin
    finally:
        reg_module._registry = orig_registry



def test_plugin_get_model_scenarios():
    """Plugin.get_model() の様々なシナリオを検証"""
    
    # 1. model_requirements が None の場合
    plugin_none = DummyPlugin("none_plugin", model_requirements=None)
    assert plugin_none.get_model() is None
    
    # 2. model_registry から正常にモデルが取得できる場合
    plugin_ok = DummyPlugin(
        "ok_plugin",
        model_requirements={"task": "task_ok", "model": "gemini-test"}
    )
    mock_get_model = MagicMock(return_value="gemini-actual-model")
    mock_module = MagicMock(get_model=mock_get_model)
    
    with patch.dict(sys.modules, {"backend.model_registry": mock_module, "model_registry": mock_module}):
        assert plugin_ok.get_model() == "gemini-actual-model"
        mock_get_model.assert_called_once_with("task_ok")
        
    # 3. model_registry がインポートエラーの場合（フォールバックモデルが返る）
    plugin_import_err = DummyPlugin(
        "import_err_plugin",
        model_requirements={"task": "task_import_err", "model": "gemini-fallback"}
    )
    with patch.dict(sys.modules, {"backend.model_registry": None, "model_registry": None}):
        with patch('backend.core.plugin.logger.warning') as mock_warn:
            assert plugin_import_err.get_model() == "gemini-fallback"
            mock_warn.assert_called_once()
            
    # 4. model_registry 呼び出し時に例外が発生した場合（安全にフォールバックモデルが返る）
    plugin_runtime_err = DummyPlugin(
        "runtime_err_plugin",
        model_requirements={"task": "task_runtime_err", "model": "gemini-fallback-2"}
    )
    mock_get_model_err = MagicMock(side_effect=ValueError("Invalid model request"))
    mock_module_err = MagicMock(get_model=mock_get_model_err)
    with patch.dict(sys.modules, {"backend.model_registry": mock_module_err, "model_registry": mock_module_err}):
        with patch('backend.core.plugin.logger.warning') as mock_warn:
            assert plugin_runtime_err.get_model() == "gemini-fallback-2"
            mock_warn.assert_called_once()


def test_plugin_validation_errors():
    """Plugin.validate() の例外発生ケースの検証"""
    # 1. name が実装されていない / 不正な型
    class BadNamePlugin(Plugin):
        @property
        def name(self):
            return 123  # 不正な型
        def execute(self, context):
            return context
            
    p_bad_name = BadNamePlugin()
    with pytest.raises(ValueError, match="Plugin name must be a non-empty string"):
        p_bad_name.validate()

    # 2. phase が不正な型
    class BadPhasePlugin(Plugin):
        @property
        def name(self):
            return "bad_phase_plugin"
        @property
        def phase(self):
            return "GENERATION"  # Enum ではない
        def execute(self, context):
            return context
            
    p_bad_phase = BadPhasePlugin()
    with pytest.raises(TypeError, match="Plugin phase must be a PluginPhase Enum"):
        p_bad_phase.validate()

    # 3. priority が不正な型
    class BadPriorityPlugin(Plugin):
        @property
        def name(self):
            return "bad_priority_plugin"
        @property
        def priority(self):
            return "high"  # int ではない
        def execute(self, context):
            return context
            
    p_bad_priority = BadPriorityPlugin()
    with pytest.raises(TypeError, match="Plugin priority must be an integer"):
        p_bad_priority.validate()

    # 4. model_requirements が辞書以外
    class BadReqsPlugin(Plugin):
        @property
        def name(self):
            return "bad_reqs_plugin"
        @property
        def model_requirements(self):
            return ["task", "model"]  # dict ではない
        def execute(self, context):
            return context
            
    p_bad_reqs = BadReqsPlugin()
    with pytest.raises(TypeError, match="Plugin model_requirements must be a dictionary"):
        p_bad_reqs.validate()


def test_registry_register_validation():
    """PluginRegistry.register が validate() を呼び出し、エラーがあれば防ぐことを検証"""
    registry = PluginRegistry()
    
    class InvalidPlugin(Plugin):
        @property
        def name(self):
            return ""  # 無効な名前
        def execute(self, context):
            return context
            
    p_invalid = InvalidPlugin()
    with pytest.raises(ValueError):
        registry.register(p_invalid)


def test_plugin_get_model_invalid_requirements():
    """Plugin.get_model() で model_requirements が不正な型の場合に None が返ることを検証"""
    class BadReqsGetModelPlugin(Plugin):
        @property
        def name(self):
            return "bad_reqs_get_model"
        @property
        def model_requirements(self):
            return "invalid_string"  # dict ではない
        def execute(self, context):
            return context
            
    p = BadReqsGetModelPlugin()
    assert p.get_model() is None


def test_plugin_on_error_robustness():
    """Plugin.on_error() が context=None などの無効な入力に対して頑健に動作することを検証"""
    class DummyErrorPlugin(Plugin):
        @property
        def name(self):
            return "dummy_error_plugin"
        def execute(self, context):
            return context
            
    p = DummyErrorPlugin()
    # context=None でも例外を投げずに context を返す（この場合は None を返す）
    assert p.on_error(None, RuntimeError("Test error")) is None
