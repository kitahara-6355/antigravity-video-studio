"""
Plugins Package - プラグイン集約

PROJECT_CONSTITUTION §16 準拠
"""
from .thumbnail_plugin import ThumbnailPlugin
from .opening_ending_plugin import OpeningEndingPlugin
from .music_layer_plugin import MusicLayerPlugin
from .auto_chapters_plugin import AutoChaptersPlugin
from .report_generator_plugin import ReportGeneratorPlugin

__all__ = [
    "ThumbnailPlugin",
    "OpeningEndingPlugin",
    "MusicLayerPlugin",
    "AutoChaptersPlugin",
    "ReportGeneratorPlugin",
]


def register_all_plugins():
    """全プラグインをレジストリに登録"""
    from core import register_plugin
    
    register_plugin(ThumbnailPlugin())
    register_plugin(OpeningEndingPlugin())
    register_plugin(MusicLayerPlugin())
    register_plugin(AutoChaptersPlugin())
    register_plugin(ReportGeneratorPlugin())
