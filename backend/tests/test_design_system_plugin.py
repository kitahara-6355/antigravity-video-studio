# -*- coding: utf-8 -*-
import pytest
import os
import sys
from unittest.mock import MagicMock, patch

# パス設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "design_system")))

from core import Plugin, PluginPhase, ProductionContext
from design_system.design_system_plugin import DesignSystemPlugin, BrandConsistencyPlugin

def test_design_system_plugin_metadata():
    plugin = DesignSystemPlugin()
    assert plugin.name == "design_system"
    assert plugin.phase == PluginPhase.PRE_PROCESS
    assert plugin.priority == 1
    assert plugin.can_execute(MagicMock()) is True

def test_design_system_plugin_execute_success():
    context = MagicMock(spec=ProductionContext)
    context.mood = "elegant"
    context.mood_settings = None
    
    # 拡張データのモック
    extensions = {}
    def mock_set_extension(key, val):
        extensions[key] = val
    context.set_extension.side_effect = mock_set_extension

    mock_tokens = {
        "color_palette": {"primary": "#ffffff"},
        "typography": {"font_size": 24},
        "motion": {"fade": "0.5s"},
        "imagen_prompt_suffix": "detailed",
        "veo_prompt_suffix": "high res"
    }

    plugin = DesignSystemPlugin()
    # design_token_manager.get_tokens のモック
    with patch("design_system.design_token_manager.design_token_manager.get_tokens", return_value=mock_tokens) as mock_get_tokens:
        res = plugin.execute(context)
        
        mock_get_tokens.assert_called_once_with("elegant")
        assert res.mood_settings == mock_tokens
        assert extensions["color_palette"] == {"primary": "#ffffff"}
        assert extensions["typography"] == {"font_size": 24}
        assert extensions["motion"] == {"fade": "0.5s"}
        assert extensions["imagen_prompt_suffix"] == "detailed"
        assert extensions["veo_prompt_suffix"] == "high res"

def test_design_system_plugin_execute_no_tokens():
    context = MagicMock(spec=ProductionContext)
    context.mood = "unknown"
    context.mood_settings = None
    
    plugin = DesignSystemPlugin()
    with patch("design_system.design_token_manager.design_token_manager.get_tokens", return_value=None):
        res = plugin.execute(context)
        assert res.mood_settings is None

def test_brand_consistency_plugin_metadata():
    plugin = BrandConsistencyPlugin()
    assert plugin.name == "brand_consistency"
    assert plugin.phase == PluginPhase.POST_PROCESS
    assert plugin.priority == 50

def test_brand_consistency_plugin_can_execute():
    plugin = BrandConsistencyPlugin()
    
    context_executable = MagicMock(spec=ProductionContext)
    context_executable.mood_settings = {"some": "settings"}
    
    context_non_executable = MagicMock(spec=ProductionContext)
    context_non_executable.mood_settings = None
    
    assert plugin.can_execute(context_executable) is True
    assert plugin.can_execute(context_non_executable) is False

def test_brand_consistency_plugin_execute_passed():
    context = MagicMock(spec=ProductionContext)
    
    # get_extension のモック
    extensions = {
        "color_palette": {"primary": "#ffffff"},
        "typography": {"font_size": 24}
    }
    def mock_get_extension(key, default=None):
        return extensions.get(key, default)
    context.get_extension.side_effect = mock_get_extension
    
    recorded_extensions = {}
    def mock_set_extension(key, val):
        recorded_extensions[key] = val
    context.set_extension.side_effect = mock_set_extension

    plugin = BrandConsistencyPlugin()
    res = plugin.execute(context)
    
    assert recorded_extensions["brand_check_passed"] is True
    assert len(recorded_extensions["brand_check_issues"]) == 0

def test_brand_consistency_plugin_execute_failed():
    context = MagicMock(spec=ProductionContext)
    
    # 空の拡張データ（整合性エラーが出るはず）
    extensions = {}
    def mock_get_extension(key, default=None):
        return extensions.get(key, default)
    context.get_extension.side_effect = mock_get_extension
    
    recorded_extensions = {}
    def mock_set_extension(key, val):
        recorded_extensions[key] = val
    context.set_extension.side_effect = mock_set_extension

    plugin = BrandConsistencyPlugin()
    res = plugin.execute(context)
    
    assert recorded_extensions["brand_check_passed"] is False
    assert "Color palette not applied" in recorded_extensions["brand_check_issues"]
    assert "Typography not applied" in recorded_extensions["brand_check_issues"]


def test_design_system_plugin_import_error_fallback():
    import sys
    
    # 既存のモジュールをバックアップ
    original_model_registry = sys.modules.get("model_registry")
    original_design_system_plugin = sys.modules.get("design_system.design_system_plugin")
    
    try:
        # sys.modulesから削除してインポート失敗状態を作る
        if "model_registry" in sys.modules:
            del sys.modules["model_registry"]
        sys.modules["model_registry"] = None
        
        if "design_system.design_system_plugin" in sys.modules:
            del sys.modules["design_system.design_system_plugin"]
            
        # モジュールをインポート
        import design_system.design_system_plugin as dsp
        
        # get_model の挙動を確認。**直書きの既定値に逃げない**（R1.5-C6）。
        # 2026-08-28 まで gemini-2.5-flash を直書きしており、2026-10-16 に
        # 提供終了するモデルが本番の実行経路に居座っていた
        from model_policy import resolve
        assert dsp.get_model("branding") == resolve("branding").model
        assert not dsp.get_model("branding").startswith("gemini-2.5")
        
    finally:
        # sys.modulesを元に戻す
        if original_model_registry is not None:
            sys.modules["model_registry"] = original_model_registry
        elif "model_registry" in sys.modules:
            del sys.modules["model_registry"]
            
        if original_design_system_plugin is not None:
            sys.modules["design_system.design_system_plugin"] = original_design_system_plugin
        elif "design_system.design_system_plugin" in sys.modules:
            del sys.modules["design_system.design_system_plugin"]

def test_design_system_plugin_execute_partial_tokens():
    """一部のトークンが欠落している場合でも、デフォルト値が正しく設定されること"""
    context = MagicMock(spec=ProductionContext)
    context.mood = "elegant"
    context.mood_settings = None
    
    extensions = {}
    def mock_set_extension(key, val):
        extensions[key] = val
    context.set_extension.side_effect = mock_set_extension

    # 部分的に欠落したトークン（color_palette のみあり、他はなし）
    mock_tokens = {
        "color_palette": {"primary": "#ffffff"}
    }

    plugin = DesignSystemPlugin()
    with patch("design_system.design_token_manager.design_token_manager.get_tokens", return_value=mock_tokens):
        res = plugin.execute(context)
        
        assert res.mood_settings == mock_tokens
        assert extensions["color_palette"] == {"primary": "#ffffff"}
        assert extensions["typography"] == {}  # デフォルト値
        assert extensions["motion"] == {}      # デフォルト値
        assert extensions["imagen_prompt_suffix"] == ""  # デフォルト値
        assert extensions["veo_prompt_suffix"] == ""    # デフォルト値


def test_brand_consistency_plugin_execute_partial_failed():
    """カラーのみ適用され、タイポグラフィが適用されていない場合、部分的にエラーが発生すること"""
    context = MagicMock(spec=ProductionContext)
    
    extensions = {
        "color_palette": {"primary": "#ffffff"}
        # typography は欠落
    }
    def mock_get_extension(key, default=None):
        return extensions.get(key, default)
    context.get_extension.side_effect = mock_get_extension
    
    recorded_extensions = {}
    def mock_set_extension(key, val):
        recorded_extensions[key] = val
    context.set_extension.side_effect = mock_set_extension

    plugin = BrandConsistencyPlugin()
    res = plugin.execute(context)
    
    assert recorded_extensions["brand_check_passed"] is False
    assert "Typography not applied" in recorded_extensions["brand_check_issues"]
    assert "Color palette not applied" not in recorded_extensions["brand_check_issues"]


def test_brand_consistency_plugin_model_requirements():
    """ブランド整合性チェックプラグインのモデル要件が正しく設定されていること"""
    plugin = BrandConsistencyPlugin()
    reqs = plugin.model_requirements
    
    assert reqs["task"] == "brand_check"
    assert reqs["api_type"] == "gemini"
    assert "model" in reqs
    assert "fallback" in reqs

