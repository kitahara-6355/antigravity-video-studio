"""
M2.5: Video Processor テスト — 15テスト

video_processor.py (297 stmts, 229 missed → 19%) のカバレッジ改善。
VideoProcessor のユーティリティ関数・タスク管理・フィルタ生成を網羅。

外部依存: FFmpeg → subprocess.runをモック。
"""

import pytest
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from video_processor import (
    VideoProcessor, ProcessingPhase, ProcessingTask,
    MoodSettings, VideoMood, MOOD_SETTINGS,
)


@pytest.fixture
def processor(tmp_path):
    """テスト用VideoProcessor"""
    return VideoProcessor(output_dir=str(tmp_path))


# ============================================================
# ムード設定テスト
# ============================================================

class TestMoodSettings:
    """MOOD_SETTINGS: ムード定義"""

    def test_all_moods_defined(self):
        """全ムードが定義されている"""
        assert "elegant" in MOOD_SETTINGS
        assert "dynamic" in MOOD_SETTINGS
        assert "dramatic" in MOOD_SETTINGS

    def test_mood_settings_attributes(self):
        """MoodSettings: 属性値が正しい"""
        elegant = MOOD_SETTINGS["elegant"]
        assert elegant.name == "エレガント"
        assert elegant.color_preset == "warm"
        assert elegant.transition == "fade"
        assert 0 < elegant.logo_opacity <= 1.0

    def test_get_mood_settings_valid(self, processor):
        """get_mood_settings: 有効なムード"""
        settings = processor.get_mood_settings("dynamic")
        assert settings.name == "ダイナミック"

    def test_get_mood_settings_default(self, processor):
        """get_mood_settings: 無効なムード → elegant"""
        settings = processor.get_mood_settings("nonexistent")
        assert settings.name == "エレガント"

    def test_get_mood_settings_case_insensitive(self, processor):
        """get_mood_settings: 大文字小文字を区別しない"""
        settings = processor.get_mood_settings("DRAMATIC")
        assert settings.name == "ドラマチック"


# ============================================================
# タスク管理テスト
# ============================================================

class TestTaskManagement:
    """VideoProcessor: タスクCRUD"""

    def test_create_task(self, processor):
        """create_task: タスク作成"""
        task = processor.create_task(
            task_id="test1",
            video_paths=["/path/to/video.mp4"],
            mood="elegant",
        )
        assert task.task_id == "test1"
        assert task.phase == ProcessingPhase.IDLE
        assert task.progress == 0

    def test_create_task_with_assets(self, processor):
        """create_task: ゲストアセット付き"""
        task = processor.create_task(
            task_id="test2",
            video_paths=["/path/to/video.mp4"],
            mood="dynamic",
            guest_assets=["/asset1.png", "/asset2.png"],
            output_name="my_video",
        )
        assert len(task.guest_assets) == 2
        assert task.output_name == "my_video"

    def test_get_task_existing(self, processor):
        """get_task: 存在するタスク"""
        processor.create_task("test3", ["/v.mp4"], "elegant")
        task = processor.get_task("test3")
        assert task is not None
        assert task.task_id == "test3"

    def test_get_task_not_found(self, processor):
        """get_task: 存在しないタスク → None"""
        assert processor.get_task("nonexistent") is None


# ============================================================
# カラーフィルタテスト
# ============================================================

class TestColorFilter:
    """VideoProcessor._get_color_filter: ムード別FFmpegフィルタ"""

    def test_warm_filter(self, processor):
        """warm: カラーバランスフィルタ"""
        settings = MoodSettings(name="test", color_preset="warm", transition="", music_style="", telop_style="")
        f = processor._get_color_filter(settings)
        assert "colorbalance" in f
        assert "rs=0.1" in f

    def test_vibrant_filter(self, processor):
        """vibrant: 彩度強化フィルタ"""
        settings = MoodSettings(name="test", color_preset="vibrant", transition="", music_style="", telop_style="")
        f = processor._get_color_filter(settings)
        assert "saturation=1.3" in f

    def test_cinematic_filter(self, processor):
        """cinematic: シネマティックフィルタ"""
        settings = MoodSettings(name="test", color_preset="cinematic", transition="", music_style="", telop_style="")
        f = processor._get_color_filter(settings)
        assert "saturation=0.9" in f

    def test_unknown_preset(self, processor):
        """未知のプリセット → 空文字列"""
        settings = MoodSettings(name="test", color_preset="unknown", transition="", music_style="", telop_style="")
        f = processor._get_color_filter(settings)
        assert f == ""


# ============================================================
# 進捗コールバックテスト
# ============================================================

class TestProgressCallback:
    """VideoProcessor: 進捗通知"""

    def test_set_and_notify(self, processor):
        """set_progress_callback + _notify_progress"""
        callback = MagicMock()
        processor.set_progress_callback(callback)
        task = processor.create_task("cb_test", ["/v.mp4"], "elegant")
        processor._notify_progress(task)
        callback.assert_called_once_with(task)

    def test_notify_without_callback(self, processor):
        """_notify_progress: コールバックなし → エラーなし"""
        task = processor.create_task("cb_test2", ["/v.mp4"], "elegant")
        processor._notify_progress(task)  # 例外なし
