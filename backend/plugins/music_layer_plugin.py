"""
Music Layer Plugin - 音楽レイヤー管理プラグイン

PROJECT_CONSTITUTION §16 準拠:
- 非破壊的編集
- ムード連動
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Optional
from pathlib import Path
import random


class MusicLayerPlugin(Plugin):
    """
    音楽レイヤー管理プラグイン（非破壊的）
    
    ムード設定に基づいてBGMを選択し、レイヤーとして設定する。
    実際の音声合成は最終エクスポート時に行う。
    """
    
    name = "music_layer"
    phase = PluginPhase.GENERATION
    priority = 25  # サムネイル(10)とOP/ED(20)の後
    
    # 音楽ライブラリパス
    MUSIC_LIBRARY = Path("assets/music")
    
    # ムード別音楽マッピング
    MOOD_MAPPING = {
        "elegant": {
            "style": "classical",
            "tracks": ["piano_elegant_01.mp3", "strings_calm_01.mp3"],
            "volume": 0.3
        },
        "dynamic": {
            "style": "upbeat",
            "tracks": ["pop_energetic_01.mp3", "electronic_upbeat_01.mp3"],
            "volume": 0.4
        },
        "dramatic": {
            "style": "orchestral",
            "tracks": ["epic_cinematic_01.mp3", "orchestra_dramatic_01.mp3"],
            "volume": 0.35
        }
    }
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """音楽レイヤーを設定"""
        if context is None:
            self.log("Context is None, skipping execution", level="error")
            return context

        try:
            # 音楽が無効化されている場合はスキップ
            if not context.get_extension("music_enabled", True):
                self.log("Music disabled, skipping")
                return context
            
            mood = getattr(context, "mood", None)
            selected_mood_config = self._get_mood_config(mood)
            
            if not isinstance(selected_mood_config, dict):
                self.log(f"Invalid mood configuration type: {type(selected_mood_config)}", level="error")
                return context
            
            selected_track = self._select_track(selected_mood_config)
            if selected_track is None:
                return context

            music_path = self.MUSIC_LIBRARY / selected_track
            
            # 音楽ファイルの存在確認（非破壊設計のため、存在しなくても設定は行うが警告ログを出す）
            if not music_path.exists():
                self.log(f"BGM file not found: {music_path}. Subsequent export processes may fail.", level="warning")
            
            self._apply_music_settings(context, music_path, selected_mood_config)
            self._apply_ducking_settings(context)
            
            style = selected_mood_config.get("style", "classical")
            self.log(f"Music layer set: {selected_track} (style: {style})")
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            self.log(f"Configuration or context error in MusicLayerPlugin: {str(e)}", level="error")
        except Exception as e:
            self.log(f"Unhandled exception in MusicLayerPlugin: {str(e)}", level="error")
        
        return context

    def _get_mood_config(self, mood: Optional[str]) -> dict:
        """ムード設定の取得とフォールバック"""
        # MOOD_MAPPING が正しく辞書であることを安全に保証
        fallback_mood_config = self.MOOD_MAPPING.get("elegant", {}) if isinstance(self.MOOD_MAPPING, dict) else {}
        selected_mood_config = self.MOOD_MAPPING.get(mood, fallback_mood_config) if isinstance(self.MOOD_MAPPING, dict) else fallback_mood_config
        return selected_mood_config

    def _select_track(self, mood_config: dict) -> Optional[str]:
        """設定からトラックを検証・選択"""
        tracks = mood_config.get("tracks", [])
        if not isinstance(tracks, list):
            self.log(f"Invalid tracks configuration type: {type(tracks)}", level="error")
            return None

        if not tracks:
            self.log("No tracks available for mood", level="warning")
            return None

        selected_track = random.choice(tracks)
        if not isinstance(selected_track, str):
            self.log(f"Invalid track type: {type(selected_track)}", level="error")
            return None

        return selected_track

    def _apply_music_settings(self, context: ProductionContext, music_path: Path, mood_config: dict) -> None:
        """音楽レイヤーの基本設定を適用"""
        style = mood_config.get("style", "classical")
        volume = mood_config.get("volume", 0.3)
        if not isinstance(volume, (int, float)) or not (0.0 <= volume <= 1.0):
            self.log(f"Invalid volume value: {volume}, falling back to 0.3", level="warning")
            volume = 0.3
            
        context.set_extension("music_layer", str(music_path))
        context.set_extension("music_volume", volume)
        context.set_extension("music_style", style)
        context.set_extension("music_applied_to", ["opening", "ending", "main"])

    def _apply_ducking_settings(self, context: ProductionContext) -> None:
        """ダッキング設定を適用"""
        context.set_extension("music_ducking", {
            "enabled": True,
            "duck_level": 0.15,  # ナレーション時の音量
            "attack_ms": 200,
            "release_ms": 500
        })
    
    def can_execute(self, context: ProductionContext) -> bool:
        """OP/EDまたは本編がある場合のみ実行"""
        if context is None:
            return False
        
        opening = getattr(context, "opening", None)
        ending = getattr(context, "ending", None)
        video_paths = getattr(context, "video_paths", [])
        
        return (
            opening is not None or
            ending is not None or
            (isinstance(video_paths, list) and len(video_paths) > 0)
        )

