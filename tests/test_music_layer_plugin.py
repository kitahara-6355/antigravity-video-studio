import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# backend パスを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core import ProductionContext, PluginPhase
from plugins.music_layer_plugin import MusicLayerPlugin


def test_plugin_metadata():
    """プラグインの基本メタデータのテスト"""
    plugin = MusicLayerPlugin()
    assert plugin.name == "music_layer"
    assert plugin.phase == PluginPhase.GENERATION
    assert plugin.priority == 25


def test_can_execute():
    """can_execute メソッドの条件分岐テスト"""
    plugin = MusicLayerPlugin()
    
    # 1. すべて None / 空の場合 -> False
    context = ProductionContext()
    context.opening = None
    context.ending = None
    context.video_paths = []
    assert plugin.can_execute(context) is False
    
    # 2. opening が設定されている場合 -> True
    context = ProductionContext()
    context.opening = "opening.mp4"
    context.ending = None
    context.video_paths = []
    assert plugin.can_execute(context) is True
    
    # 3. ending が設定されている場合 -> True
    context = ProductionContext()
    context.opening = None
    context.ending = "ending.mp4"
    context.video_paths = []
    assert plugin.can_execute(context) is True
    
    # 4. video_paths が設定されている場合 -> True
    context = ProductionContext()
    context.opening = None
    context.ending = None
    context.video_paths = ["main.mp4"]
    assert plugin.can_execute(context) is True


def test_execute_music_disabled():
    """音楽が無効化されている場合、処理がスキップされることのテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    
    # music_enabled を False に設定
    context.set_extension("music_enabled", False)
    
    # 元々の拡張機能の値を記録
    original_extensions = dict(context._extensions)
    
    # 実行
    with patch.object(plugin, 'log') as mock_log:
        result_context = plugin.execute(context)
        mock_log.assert_any_call("Music disabled, skipping")
    
    # コンテキストが変更されていないことを確認
    assert result_context == context
    assert result_context._extensions == original_extensions


@pytest.mark.parametrize("mood, expected_style, expected_volume, expected_track", [
    ("elegant", "classical", 0.3, "piano_elegant_01.mp3"),
    ("dynamic", "upbeat", 0.4, "pop_energetic_01.mp3"),
    ("dramatic", "orchestral", 0.35, "epic_cinematic_01.mp3"),
    ("unknown_mood", "classical", 0.3, "piano_elegant_01.mp3"),  # フォールバック先は elegant
])
def test_execute_mood_mappings(mood, expected_style, expected_volume, expected_track):
    """各ムード（正常および未知のムードでのフォールバック）のテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    context.mood = mood
    
    # random.choice をパッチして、リストの最初のトラックを常に選ぶようにする
    with patch("random.choice", side_effect=lambda x: x[0]):
        with patch.object(plugin, 'log') as mock_log:
            result_context = plugin.execute(context)
            
            # ログの検証
            mock_log.assert_any_call(f"Music layer set: {expected_track} (style: {expected_style})")
            
    # 各種設定が context.extensions に反映されていることを確認
    music_path = Path("assets/music") / expected_track
    assert result_context.get_extension("music_layer") == str(music_path)
    assert result_context.get_extension("music_volume") == expected_volume
    assert result_context.get_extension("music_style") == expected_style
    assert result_context.get_extension("music_applied_to") == ["opening", "ending", "main"]
    
    # ダッキング設定の検証
    ducking = result_context.get_extension("music_ducking")
    assert ducking["enabled"] is True
    assert ducking["duck_level"] == 0.15
    assert ducking["attack_ms"] == 200
    assert ducking["release_ms"] == 500


def test_execute_no_tracks():
    """ムード設定でトラックが空の場合のテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    context.mood = "elegant"
    
    # MOOD_MAPPING を一時的に書き換えて tracks を空にする
    custom_mapping = {
        "elegant": {
            "style": "classical",
            "tracks": [],
            "volume": 0.3
        }
    }
    
    with patch.dict(plugin.MOOD_MAPPING, custom_mapping, clear=True):
        with patch.object(plugin, 'log') as mock_log:
            result_context = plugin.execute(context)
            mock_log.assert_any_call("No tracks available for mood", level="warning")
            
    # extensions に音楽設定が追加されていないことを確認
    assert result_context.get_extension("music_layer") is None


def test_execute_non_existent_music_file():
    """BGMファイルが存在しない場合に警告ログが出力されることのテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    context.mood = "elegant"
    
    # 存在しないパスをテストするために random.choice をパッチ
    with patch("random.choice", return_value="non_existent_bgm_12345.mp3"):
        with patch.object(plugin, 'log') as mock_log:
            result_context = plugin.execute(context)
            # 警告ログが出力されていること
            mock_log.assert_any_call("BGM file not found: assets\\music\\non_existent_bgm_12345.mp3. Subsequent export processes may fail.", level="warning")
            
    # 設定自体はセットされていること
    assert result_context.get_extension("music_layer") == str(Path("assets/music/non_existent_bgm_12345.mp3"))


@pytest.mark.parametrize("invalid_volume", [-0.5, 1.5, "high"])
def test_execute_invalid_volume(invalid_volume):
    """無効な音量設定の場合にデフォルト値0.3にフォールバックされることのテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    context.mood = "elegant"
    
    custom_mapping = {
        "elegant": {
            "style": "classical",
            "tracks": ["piano_elegant_01.mp3"],
            "volume": invalid_volume
        }
    }
    
    with patch.dict(plugin.MOOD_MAPPING, custom_mapping, clear=True):
        with patch.object(plugin, 'log') as mock_log:
            result_context = plugin.execute(context)
            # 警告ログの出力確認
            mock_log.assert_any_call(f"Invalid volume value: {invalid_volume}, falling back to 0.3", level="warning")
            
    # フォールバックされた値がセットされていること
    assert result_context.get_extension("music_volume") == 0.3


def test_execute_specific_exception_handling():
    """具体的な例外が発生したときにエラーログが出力され、contextが返されることのテスト"""
    plugin = MusicLayerPlugin()
    context = ProductionContext()
    context.mood = "elegant"
    
    # context.get_extension 呼び出し時に TypeError を発生させる
    with patch.object(context, 'get_extension', side_effect=TypeError("Mock TypeError")):
        with patch.object(plugin, 'log') as mock_log:
            result_context = plugin.execute(context)
            # 例外がキャッチされ、エラーログが出力されていること
            mock_log.assert_any_call("Configuration or context error in MusicLayerPlugin: Mock TypeError", level="error")
            
    # クラッシュせずに context が返ること
    assert result_context == context

