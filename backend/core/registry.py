"""
Plugin Registry - プラグイン管理とモデル自動登録

PROJECT_CONSTITUTION §16 準拠:
- プラグイン登録・管理
- モデル要件の自動収集
- 陳腐化チェック連携
"""
from typing import Dict, List, Optional, Type
from .plugin import Plugin, PluginPhase
from .context import ProductionContext
import logging

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    プラグインレジストリ
    
    PROJECT_CONSTITUTION §16 準拠:
    - プラグインの登録と管理
    - モデル要件の自動収集
    - フェーズ順の実行制御
    
    使用例:
        registry = PluginRegistry()
        registry.register(ThumbnailPlugin())
        registry.register(OpeningPlugin())
        
        context = registry.execute_all(context)
    """
    
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._model_requirements: Dict[str, Dict] = {}
    
    # === プラグイン登録 ===
    
    def register(self, plugin: Plugin) -> None:
        """
        プラグインを登録
        
        Args:
            plugin: 登録するプラグインインスタンス
        """
        if plugin is None:
            raise TypeError("Plugin cannot be None")
            
        # プラグインの自己整合性検証を実行
        if hasattr(plugin, "validate") and callable(plugin.validate):
            plugin.validate()
        else:
            if not getattr(plugin, "name", None) or not isinstance(plugin.name, str):
                raise ValueError("Plugin must have a non-empty string 'name' attribute")
        
        if plugin.name in self._plugins:
            logger.warning(f"Plugin {plugin.name} already registered, overwriting")
        
        self._plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin}")
        
        # モデル要件を自動収集
        self._collect_model_requirements(plugin)
    
    def unregister(self, name: str) -> Optional[Plugin]:
        """プラグインを登録解除"""
        if name is None or not isinstance(name, str):
            raise TypeError("Plugin name must be a string")
        if not name:
            raise ValueError("Plugin name cannot be empty")
        return self._plugins.pop(name, None)
    
    def get(self, name: str) -> Optional[Plugin]:
        """プラグインを取得"""
        if name is None or not isinstance(name, str):
            raise TypeError("Plugin name must be a string")
        if not name:
            raise ValueError("Plugin name cannot be empty")
        return self._plugins.get(name)
    
    def list_plugins(self) -> List[Plugin]:
        """全プラグインをリスト"""
        return list(self._plugins.values())
    
    # === モデル要件自動収集（PROJECT_CONSTITUTION §16.3）===
    
    def _collect_model_requirements(self, plugin: Plugin) -> None:
        """
        プラグインからモデル要件を自動収集
        
        ModelRegistryに登録し、陳腐化チェックを実行
        """
        try:
            req = plugin.model_requirements
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError) as e:
            logger.warning(f"Could not retrieve model requirements from plugin: {e}")
            return
            
        if not req or not isinstance(req, dict):
            return
        
        try:
            plugin_name = plugin.name
        except (AttributeError, TypeError, ValueError, NotImplementedError, RuntimeError):
            plugin_name = plugin.__class__.__name__

        task = req.get("task", plugin_name)
        model = req.get("model")
        
        if not model:
            return
        
        # モデル要件を保存
        self._model_requirements[task] = {
            "model": model,
            "fallback": req.get("fallback"),
            "api_type": req.get("api_type", "gemini"),
            "plugin": plugin_name
        }
        
        # ModelRegistryに登録
        try:
            from model_registry import get_registry
            registry = get_registry()
            registry.register_plugin_requirement(plugin)
            logger.info(f"Registered model requirement: {task} -> {model}")
        except ImportError:
            logger.warning("ModelRegistry not available for model registration")
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning(f"Invalid model requirement configuration in plugin {plugin_name}: {e}", exc_info=True)
        except (KeyError, RuntimeError, OSError) as e:
            logger.exception(f"Unexpected error registering model requirement for plugin {plugin_name}: {e}")
    
    def get_model_requirements(self) -> Dict[str, Dict]:
        """収集したモデル要件を取得"""
        return self._model_requirements.copy()
    
    # === プラグイン実行 ===
    
    def get_plugins_by_phase(self, phase: PluginPhase) -> List[Plugin]:
        """指定フェーズのプラグインを優先度順で取得"""
        plugins = [p for p in self._plugins.values() if p.phase == phase]
        return sorted(plugins, key=lambda p: p.priority)
    
    def execute_phase(self, phase: PluginPhase, context: ProductionContext) -> ProductionContext:
        """
        指定フェーズの全プラグインを実行
        
        Args:
            phase: 実行するフェーズ
            context: 制作コンテキスト
            
        Returns:
            更新されたコンテキスト
        """
        plugins = self.get_plugins_by_phase(phase)
        logger.info(f"Executing phase {phase.value} with {len(plugins)} plugins")
        
        for plugin in plugins:
            if not plugin.can_execute(context):
                logger.info(f"Skipping plugin {plugin.name} (can_execute=False)")
                continue
            
            try:
                logger.info(f"Executing plugin: {plugin.name}")
                new_context = plugin.execute(context)
                if new_context is not None:
                    context = new_context
                else:
                    logger.warning(f"Plugin {plugin.name} execute() returned None context")
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, IndexError, OSError, NameError, ArithmeticError, AssertionError) as e:
                logger.exception(f"Plugin {plugin.name} failed with exception: {e}")
                try:
                    fallback_context = plugin.on_error(context, e)
                    if fallback_context is not None:
                        context = fallback_context
                    else:
                        logger.warning(f"Plugin {plugin.name} on_error() returned None context")
                        context.set_extension(f"{plugin.name}_error", str(e))
                except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OSError) as on_error_err:
                    logger.error(f"Plugin {plugin.name} on_error call failed: {on_error_err}")
                    context.set_extension(
                        f"{plugin.name}_error", 
                        f"Execute error: {e}. On_error error: {on_error_err}"
                    )
        
        return context
    
    def execute_all(self, context: ProductionContext) -> ProductionContext:
        """
        全フェーズの全プラグインを順次実行
        
        Args:
            context: 制作コンテキスト
            
        Returns:
            更新されたコンテキスト
        """
        phases = [
            PluginPhase.PRE_PROCESS,
            PluginPhase.ANALYSIS,
            PluginPhase.GENERATION,
            PluginPhase.POST_PROCESS,
            PluginPhase.FINALIZATION
        ]
        
        for phase in phases:
            context.advance_phase(phase.value)
            context = self.execute_phase(phase, context)
        
        return context
    
    # === 診断 ===
    
    def get_status(self) -> Dict:
        """レジストリのステータスを取得"""
        plugins_by_phase = {}
        for phase in PluginPhase:
            plugins = self.get_plugins_by_phase(phase)
            plugins_by_phase[phase.value] = [
                {"name": p.name, "priority": p.priority}
                for p in plugins
            ]
        
        return {
            "total_plugins": len(self._plugins),
            "model_requirements": len(self._model_requirements),
            "plugins_by_phase": plugins_by_phase
        }


# グローバルレジストリインスタンス
_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """グローバルプラグインレジストリを取得"""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def register_plugin(plugin: Plugin) -> None:
    """プラグインを登録（ショートカット関数）"""
    get_plugin_registry().register(plugin)
