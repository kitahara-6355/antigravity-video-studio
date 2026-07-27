"""
Core Package - コアフレームワーク

PROJECT_CONSTITUTION §16 準拠:
- ProductionContext: 制作コンテキスト
- Plugin: プラグインベースクラス
- PluginRegistry: プラグイン管理
"""
from .context import ProductionContext, ProductionPhase
from .plugin import Plugin, PluginPhase
from .registry import PluginRegistry, get_plugin_registry, register_plugin

__all__ = [
    "ProductionContext",
    "ProductionPhase",
    "Plugin",
    "PluginPhase",
    "PluginRegistry",
    "get_plugin_registry",
    "register_plugin",
]
