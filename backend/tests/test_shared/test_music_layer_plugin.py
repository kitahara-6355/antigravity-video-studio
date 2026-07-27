import pytest
from unittest.mock import patch
from pathlib import Path
from plugins.music_layer_plugin import MusicLayerPlugin
from core.context import ProductionContext

def test_music_layer_plugin_can_execute():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext()
    
    # すべて None/空 の場合 (can_execute は False)
    ctx.opening = None
    ctx.ending = None
    ctx.video_paths = []
    assert not plugin.can_execute(ctx)
    
    # opening のみ存在する場合
    ctx.opening = "opening_path"
    ctx.ending = None
    ctx.video_paths = []
    assert plugin.can_execute(ctx)
    
    # ending のみ存在する場合
    ctx.opening = None
    ctx.ending = "ending_path"
    ctx.video_paths = []
    assert plugin.can_execute(ctx)
    
    # video_paths のみ存在する場合
    ctx.opening = None
    ctx.ending = None
    ctx.video_paths = ["main.mp4"]
    assert plugin.can_execute(ctx)

def test_music_layer_plugin_execute_disabled():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext()
    
    # 音楽が無効化されている場合
    ctx.set_extension("music_enabled", False)
    
    # executeを実行
    res = plugin.execute(ctx)
    assert res == ctx
    # 音楽の設定が拡張パラメータに追加されていないことを確認
    assert ctx.get_extension("music_layer") is None

def test_music_layer_plugin_execute_elegant_mood():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    
    # tracksがある状態で実行
    res = plugin.execute(ctx)
    assert res == ctx
    
    music_layer = ctx.get_extension("music_layer")
    assert music_layer is not None
    
    # パスが正しく assets/music 内を指していること (OS依存を排除)
    music_path = Path(music_layer)
    assert "assets" in music_path.parts and "music" in music_path.parts
    
    assert ctx.get_extension("music_volume") == 0.3
    assert ctx.get_extension("music_style") == "classical"
    assert ctx.get_extension("music_applied_to") == ["opening", "ending", "main"]
    
    ducking = ctx.get_extension("music_ducking")
    assert ducking["enabled"] is True
    assert ducking["duck_level"] == 0.15

def test_music_layer_plugin_execute_dynamic_mood():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="dynamic")
    
    res = plugin.execute(ctx)
    assert ctx.get_extension("music_volume") == 0.4
    assert ctx.get_extension("music_style") == "upbeat"

def test_music_layer_plugin_execute_dramatic_mood():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="dramatic")
    
    res = plugin.execute(ctx)
    assert ctx.get_extension("music_volume") == 0.35
    assert ctx.get_extension("music_style") == "orchestral"

def test_music_layer_plugin_execute_fallback_mood():
    # 定義されていないムードの場合、elegantにフォールバックすること
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="unknown_mood")
    
    res = plugin.execute(ctx)
    assert ctx.get_extension("music_volume") == 0.3
    assert ctx.get_extension("music_style") == "classical"

def test_music_layer_plugin_execute_no_tracks():
    # tracksが空の場合の分岐網羅
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    
    # MOOD_MAPPINGのelegantのtracksを空にする
    with patch.dict(plugin.MOOD_MAPPING["elegant"], {"tracks": []}):
        res = plugin.execute(ctx)
        # tracksが空なので、拡張パラメータは設定されないはず
        assert ctx.get_extension("music_layer") is None

def test_music_layer_plugin_execute_none_mood():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood=None)
    
    res = plugin.execute(ctx)
    assert ctx.get_extension("music_volume") == 0.3
    assert ctx.get_extension("music_style") == "classical"

def test_music_layer_plugin_execute_missing_config_keys():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    
    # elegant の config から volume と style を取り除く
    with patch.dict(plugin.MOOD_MAPPING["elegant"], {"tracks": ["piano_elegant_01.mp3"]}, clear=True):
        res = plugin.execute(ctx)
        assert ctx.get_extension("music_volume") == 0.3
        assert ctx.get_extension("music_style") == "classical"

def test_music_layer_plugin_can_execute_multiple_videos():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext()
    ctx.video_paths = ["main1.mp4", "main2.mp4"]
    assert plugin.can_execute(ctx)

def test_music_layer_plugin_logging_disabled():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext()
    ctx.set_extension("music_enabled", False)
    
    with patch.object(plugin, 'log') as mock_log:
        plugin.execute(ctx)
        mock_log.assert_called_once_with("Music disabled, skipping")

def test_music_layer_plugin_logging_no_tracks():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    
    with patch.dict(plugin.MOOD_MAPPING["elegant"], {"tracks": []}):
        with patch.object(plugin, 'log') as mock_log:
            plugin.execute(ctx)
            mock_log.assert_called_once_with("No tracks available for mood", level="warning")

def test_music_layer_plugin_ducking_parameters_type():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    
    plugin.execute(ctx)
    ducking = ctx.get_extension("music_ducking")
    assert isinstance(ducking, dict)
    assert ducking["enabled"] is True
    assert isinstance(ducking["duck_level"], float)
    assert isinstance(ducking["attack_ms"], int)
    assert isinstance(ducking["release_ms"], int)
    assert 0.0 <= ducking["duck_level"] <= 1.0

def test_music_layer_plugin_volume_range():
    plugin = MusicLayerPlugin()
    for mood, config in plugin.MOOD_MAPPING.items():
        ctx = ProductionContext(mood=mood)
        plugin.execute(ctx)
        volume = ctx.get_extension("music_volume")
        assert isinstance(volume, float)
        assert 0.0 <= volume <= 1.0

def test_music_layer_plugin_execute_none_context():
    plugin = MusicLayerPlugin()
    assert plugin.execute(None) is None
    assert plugin.can_execute(None) is False

def test_music_layer_plugin_execute_invalid_mood_mapping_type():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    with patch.object(plugin, "MOOD_MAPPING", "invalid_type_not_dict"):
        res = plugin.execute(ctx)
        assert res == ctx
        assert ctx.get_extension("music_layer") is None

def test_music_layer_plugin_execute_invalid_tracks_type():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    with patch.dict(plugin.MOOD_MAPPING["elegant"], {"tracks": "not_a_list_string"}):
        res = plugin.execute(ctx)
        assert res == ctx
        assert ctx.get_extension("music_layer") is None

def test_music_layer_plugin_execute_invalid_track_element_type():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    with patch.dict(plugin.MOOD_MAPPING["elegant"], {"tracks": [12345]}):
        res = plugin.execute(ctx)
        assert res == ctx
        assert ctx.get_extension("music_layer") is None

def test_music_layer_plugin_execute_unhandled_exception():
    plugin = MusicLayerPlugin()
    ctx = ProductionContext(mood="elegant")
    with patch.object(ctx, "get_extension", side_effect=RuntimeError("Mock RuntimeError")):
        with patch.object(plugin, "log") as mock_log:
            res = plugin.execute(ctx)
            assert res == ctx
            mock_log.assert_any_call("Unhandled exception in MusicLayerPlugin: Mock RuntimeError", level="error")
