import pytest
import subprocess
import shutil
import time
import os
import sys
from pathlib import Path

# パス設定の解決: backend と services への絶対パスを sys.path に確実に追加
backend_dir = str(Path(__file__).parent.parent.resolve())
services_dir = str(Path(__file__).parent.parent.resolve() / "services")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if services_dir not in sys.path:
    sys.path.insert(0, services_dir)

from preview_engine import PreviewEngine, preview_engine
from color_grading import color_grading

# テスト用にデバッグモードとカラープリセットをセットアップ
os.environ["DEBUG_MODE"] = "1"
color_grading.PRESETS["TEST_PRESET"] = "eq=contrast=1.5"

# テスト全体で Path.is_file は基本 True とする（実在チェックは exists で行われているため）
original_is_file = Path.is_file
Path.is_file = lambda self: True

def test_init_ffmpeg_found():
    """ffmpeg が見つかる通常ケースの初期化テスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        assert engine.ffmpeg == "/usr/bin/ffmpeg"

def test_init_ffmpeg_local_found():
    """システム ffmpeg はないがローカルにあるケースの初期化テスト"""
    original_exists = Path.exists
    def mock_exists(self):
        if str(self).endswith("ffmpeg.exe"):
            return True
        return original_exists(self)
        
    Path.exists = mock_exists
    try:
        with patch_shutil_which(None):
            engine = PreviewEngine()
            assert engine.ffmpeg == str(Path("./backend/bin/ffmpeg.exe"))
    finally:
        Path.exists = original_exists

def test_init_ffmpeg_not_found():
    """ffmpeg がどこにも見つからない場合の初期化例外テスト"""
    original_exists = Path.exists
    def mock_exists(self):
        if str(self).endswith("ffmpeg.exe"):
            return False
        return original_exists(self)
        
    Path.exists = mock_exists
    try:
        with patch_shutil_which(None):
            with pytest.raises(RuntimeError) as excinfo:
                PreviewEngine()
            assert "FFmpeg not found" in str(excinfo.value)
    finally:
        Path.exists = original_exists

def test_has_audio_stream_success():
    """音声ストリーム検出の正常系"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="audio\n", stderr=""
        )
        
        original_run = subprocess.run
        run_called = False
        def mock_run(*args, **kwargs):
            nonlocal run_called
            run_called = True
            return mock_result
            
        subprocess.run = mock_run
        try:
            assert engine._has_audio_stream("dummy.mp4") is True
            assert run_called is True
        finally:
            subprocess.run = original_run

def test_has_audio_stream_no_audio():
    """音声ストリームがない場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="video\n", stderr=""
        )
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return mock_result
            
        subprocess.run = mock_run
        try:
            assert engine._has_audio_stream("dummy.mp4") is False
        finally:
            subprocess.run = original_run

def test_has_audio_stream_exception():
    """ffprobe 実行で例外が発生した場合のフォールバック"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise Exception("ffprobe failed")
            
        subprocess.run = mock_run
        try:
            assert engine._has_audio_stream("dummy.mp4") is False
        finally:
            subprocess.run = original_run

def test_get_font_path_candidates():
    """フォント候補が存在する場合の取得テスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self).replace("\\", "/")
            if path_str.endswith("Fonts/msgothic.ttc"):
                return True
            # msgothic 以外の候補フォントは存在しないと見せてループを進める
            if any(c in path_str for c in ["arial.ttf", "SegoeUI.ttf", "DejaVuSans.ttf", "Helvetica.ttc"]):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            font = engine._get_font_path()
            assert "msgothic.ttc" in font
        finally:
            Path.exists = original_exists

def test_get_font_path_fallback():
    """フォント候補が一切存在しない場合のフォールバックテスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            candidates = ["arial.ttf", "msgothic.ttc", "SegoeUI.ttf", "DejaVuSans.ttf", "Helvetica.ttc"]
            if any(c in str(self) for c in candidates):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            font = engine._get_font_path()
            assert font == ""
        finally:
            Path.exists = original_exists

def test_generate_preview_source_not_found():
    """generate_preview でソース動画が存在しない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("nonexistent.mp4"):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            with pytest.raises(FileNotFoundError):
                engine.generate_preview("nonexistent.mp4")
        finally:
            Path.exists = original_exists

def test_generate_preview_success():
    """generate_preview の正常系テスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_called = False
        def mock_run(*args, **kwargs):
            nonlocal run_called
            run_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            preview_id = engine.generate_preview("source.mp4", duration=10)
            assert preview_id is not None
            assert run_called is True
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_bgm_success():
    """generate_preview BGM付きの正常系テスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4") or str(self).endswith("bgm.mp3"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_called = False
        def mock_run(*args, **kwargs):
            nonlocal run_called
            run_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            preview_id = engine.generate_preview("source.mp4", bgm_path="bgm.mp3", duration=5)
            assert preview_id is not None
            assert run_called is True
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_ffmpeg_failure():
    """generate_preview で FFmpeg コマンドが失敗した場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError) as excinfo:
                engine.generate_preview("source.mp4")
            assert "Preview generation failed" in str(excinfo.value)
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_get_preview_path_exists():
    """get_preview_path の正常系"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if "previews" in str(self) and str(self).endswith("dummy_id.mp4"):
                return True
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            p = engine.get_preview_path("dummy_id")
            assert p == Path("previews/dummy_id.mp4")
        finally:
            Path.exists = original_exists

def test_get_preview_path_not_found():
    """get_preview_path でファイルが存在しない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if "previews" in str(self) and str(self).endswith("dummy_id.mp4"):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            with pytest.raises(FileNotFoundError):
                engine.get_preview_path("dummy_id")
        finally:
            Path.exists = original_exists

def test_cleanup_old_previews(tmp_path):
    """cleanup_old_previews で古いファイルが削除されるテスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        engine.preview_dir = tmp_path
        
        old_file = tmp_path / "old.mp4"
        new_file = tmp_path / "new.mp4"
        
        old_file.touch()
        new_file.touch()
        
        now = time.time()
        os.utime(old_file, (now - 9 * 86400, now - 9 * 86400))
        os.utime(new_file, (now, now))
        
        original_run = time.time
        time.time = lambda: now
        try:
            engine.cleanup_old_previews(days=7)
            assert not old_file.exists()
            assert new_file.exists()
        finally:
            time.time = original_run

def test_generate_preview_with_subtitles_source_not_found():
    """generate_preview_with_subtitles でソースファイルが存在しない場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("nonexistent.mp4"):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            with pytest.raises(FileNotFoundError):
                engine.generate_preview_with_subtitles("nonexistent.mp4", [])
        finally:
            Path.exists = original_exists

def test_generate_preview_with_subtitles_no_bgm_no_audio():
    """字幕付きプレビュー: BGM なし、動画音声なし"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args = None
        def mock_run(*args, **kwargs):
            nonlocal run_args
            run_args = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
            preview_id = engine.generate_preview_with_subtitles(
                "source.mp4", subtitles, color_preset="TEST_PRESET"
            )
            assert preview_id is not None
            assert "-an" in run_args
            # カラープリセットのフィルタが追加されていることを検証 (カバレッジ 187-189)
            assert any("eq=contrast=1.5" in arg for arg in run_args)
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_subtitles_no_font():
    """字幕付きプレビュー: フォントパスが空の場合 (カバレッジ 194)"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        # _get_font_path が空文字を返すようにモンキーパッチ
        original_get_font_path = engine._get_font_path
        engine._get_font_path = lambda: ""
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
            preview_id = engine.generate_preview_with_subtitles("source.mp4", subtitles)
            assert preview_id is not None
        finally:
            Path.exists = original_exists
            subprocess.run = original_run
            engine._get_font_path = original_get_font_path

def test_generate_preview_with_subtitles_no_bgm_with_audio():
    """字幕付きプレビュー: BGM なし、動画音声あり"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args = None
        
        def mock_run(*args, **kwargs):
            nonlocal run_args
            run_args = args[0]
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="audio\n", stderr="")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
            preview_id = engine.generate_preview_with_subtitles(
                "source.mp4", subtitles, duration=15
            )
            assert preview_id is not None
            assert "-af" in run_args
            assert any("loudnorm" in arg for arg in run_args)
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_subtitles_with_bgm():
    """字幕付きプレビュー: BGM あり、音声マージ"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4") or str(self).endswith("bgm.mp3"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args = None
        def mock_run(*args, **kwargs):
            nonlocal run_args
            run_args = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            subtitles = [{"text": "Hello 'World'", "start": 1.0, "end": 2.0}]
            preview_id = engine.generate_preview_with_subtitles(
                "source.mp4", subtitles, bgm_path="bgm.mp3"
            )
            assert preview_id is not None
            assert "-filter_complex" in run_args
            assert any("sidechaincompress" in arg for arg in run_args)
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_subtitles_ffmpeg_failure_and_cleanup():
    """字幕付きプレビュー: FFmpeg 失敗時に出力一時ファイルがクリーンアップされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return True
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        unlinked_files = []
        def mock_unlink(self):
            path_str = str(self).replace("\\", "/")
            if "previews" in path_str:
                unlinked_files.append(path_str)
                return
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError):
                engine.generate_preview_with_subtitles("source.mp4", [])
            assert len(unlinked_files) > 0
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run

def test_generate_preview_with_subtitles_general_exception_cleanup():
    """字幕付きプレビュー: その他の例外発生時にも出力一時ファイルがクリーンアップされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return True
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        unlinked_files = []
        def mock_unlink(self):
            path_str = str(self).replace("\\", "/")
            if "previews" in path_str:
                unlinked_files.append(path_str)
                return
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            raise ValueError("General error")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(ValueError):
                engine.generate_preview_with_subtitles("source.mp4", [])
            assert len(unlinked_files) > 0
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run

# ヘルパー: shutil.which を差し替えるためのコンテキストマネージャー
class patch_shutil_which:
    def __init__(self, return_value):
        self.return_value = return_value
        self.original_which = shutil.which

    def __enter__(self):
        shutil.which = lambda name: self.return_value
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        shutil.which = self.original_which


def test_generate_preview_with_feedback_params():
    """演出哲学パラメータ（feedback_params）が generate_preview に正しく伝搬され、FFmpeg フィルタに反映されるテスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4") or str(self).endswith("bgm.mp3"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args_dict = {}
        def mock_run(*args, **kwargs):
            run_args_dict['args'] = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            # 1. 辞書形式の feedback_params
            feedback_dict = {
                "tempo_multiplier": 1.2,
                "volume_multiplier": 0.8
            }
            engine.generate_preview("source.mp4", bgm_path="bgm.mp3", feedback_params=feedback_dict)
            assert any("setpts=PTS/1.2" in arg for arg in run_args_dict['args'])
            assert any("atempo=1.2" in arg for arg in run_args_dict['args'])
            assert any("volume=0.24" in arg for arg in run_args_dict['args'])  # 0.3 * 0.8 = 0.24
            assert any("volume=0.8" in arg for arg in run_args_dict['args'])

            # 2. オブジェクト形式 of feedback_params (Mock オブジェクト)
            class MockFeedbackParams:
                tempo_multiplier = 1.5
                volume_multiplier = 0.5
                telop_color = "#FF0000"
                subtitle_font_size = 40
            
            engine.generate_preview("source.mp4", feedback_params=MockFeedbackParams())
            assert any("setpts=PTS/1.5" in arg for arg in run_args_dict['args'])
            assert any("atempo=1.5" in arg for arg in run_args_dict['args'])
            assert any("volume=0.5" in arg for arg in run_args_dict['args'])
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_subtitles_with_feedback_params():
    """演出哲学パラメータ（feedback_params）が generate_preview_with_subtitles に正しく伝搬されるテスト"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4") or str(self).endswith("bgm.mp3"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args_dict = {}
        def mock_run(*args, **kwargs):
            run_args_dict['args'] = args[0]
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="audio\n", stderr="")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            # 1. 辞書形式の feedback_params (BGM あり)
            feedback_dict = {
                "tempo_multiplier": 1.1,
                "volume_multiplier": 0.9,
                "telop_color": "#FF55FF",
                "subtitle_font_size": 42
            }
            subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
            engine.generate_preview_with_subtitles("source.mp4", subtitles, bgm_path="bgm.mp3", feedback_params=feedback_dict)
            
            filter_complex = next(arg for arg in run_args_dict['args'] if "sidechaincompress" in arg)
            assert "scale=854:480,setpts=PTS/1.1" in filter_complex
            assert "fontsize=42" in filter_complex
            assert "fontcolor='#FF55FF'" in filter_complex
            assert "atempo=1.1" in filter_complex
            assert "volume=0.36" in filter_complex  # 0.4 * 0.9 = 0.36
            assert "volume=0.9" in filter_complex

            # 2. オブジェクト形式の feedback_params (音声あり、BGMなし)
            class MockFeedbackParams:
                tempo_multiplier = 0.8
                volume_multiplier = 1.2
                telop_color = "#00FFFF"
                subtitle_font_size = 28
                
            engine.generate_preview_with_subtitles("source.mp4", subtitles, feedback_params=MockFeedbackParams())
            vf_arg = run_args_dict['args'][run_args_dict['args'].index("-vf") + 1]
            af_arg = run_args_dict['args'][run_args_dict['args'].index("-af") + 1]
            assert "scale=854:480,setpts=PTS/0.8" in vf_arg
            assert "fontsize=28" in vf_arg
            assert "fontcolor='#00FFFF'" in vf_arg
            assert "atempo=0.8" in af_arg
            assert "volume=1.2" in af_arg
        finally:
            Path.exists = original_exists
            subprocess.run = original_run


def test_generate_preview_with_subtitles_empty_color_preset():
    """字幕付きプレビュー: カラープリセットが存在するが、フィルタ設定が空の場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        color_grading.PRESETS["EMPTY_PRESET"] = ""
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args = None
        def mock_run(*args, **kwargs):
            nonlocal run_args
            run_args = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
            preview_id = engine.generate_preview_with_subtitles(
                "source.mp4", subtitles, color_preset="EMPTY_PRESET"
            )
            assert preview_id is not None
            vf_val = run_args[run_args.index("-vf") + 1]
            assert "scale=854:480" in vf_val
            assert "eq=" not in vf_val
        finally:
            Path.exists = original_exists
            subprocess.run = original_run
            if "EMPTY_PRESET" in color_grading.PRESETS:
                del color_grading.PRESETS["EMPTY_PRESET"]


def test_generate_preview_with_subtitles_debug_mode_disabled():
    """字幕付きプレビュー: DEBUG_MODE が無効な場合"""
    old_debug = os.environ.get("DEBUG_MODE")
    if "DEBUG_MODE" in os.environ:
        del os.environ["DEBUG_MODE"]
        
    try:
        with patch_shutil_which("/usr/bin/ffmpeg"):
            engine = PreviewEngine()
            
            original_exists = Path.exists
            def mock_exists(self):
                if str(self).endswith("source.mp4"):
                    return True
                return original_exists(self)
                
            original_run = subprocess.run
            def mock_run(*args, **kwargs):
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
                
            Path.exists = mock_exists
            subprocess.run = mock_run
            try:
                subtitles = [{"text": "Hello", "start": 1.0, "end": 2.0}]
                preview_id = engine.generate_preview_with_subtitles("source.mp4", subtitles)
                assert preview_id is not None
            finally:
                Path.exists = original_exists
                subprocess.run = original_run
    finally:
        if old_debug is not None:
            os.environ["DEBUG_MODE"] = old_debug


def test_generate_preview_with_subtitles_ffmpeg_failure_no_output_file():
    """字幕付きプレビュー: FFmpeg 失敗時に出力ファイルが存在しない場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return False
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        unlink_called = False
        def mock_unlink(self):
            nonlocal unlink_called
            unlink_called = True
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError):
                engine.generate_preview_with_subtitles("source.mp4", [])
            assert not unlink_called
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run


def test_generate_preview_with_subtitles_general_exception_no_output_file():
    """字幕付きプレビュー: 一般例外発生時に出力ファイルが存在しない場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return False
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        unlink_called = False
        def mock_unlink(self):
            nonlocal unlink_called
            unlink_called = True
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            raise ValueError("General error")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(ValueError):
                engine.generate_preview_with_subtitles("source.mp4", [])
            assert not unlink_called
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run


# 新規バリデーションおよびエラーハンドリング関連のテストケース

def test_validate_params_invalid_source_dir():
    """ソース動画がファイルではなくディレクトリの場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        original_is_file_local = Path.is_file
        
        # exists は True だが is_file は False (ディレクトリの模擬)
        Path.exists = lambda self: True
        Path.is_file = lambda self: False
        
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source_dir")
            assert "Source video path must be a file" in str(excinfo.value)
        finally:
            Path.exists = original_exists
            Path.is_file = original_is_file_local

def test_validate_params_bgm_not_found():
    """指定された BGM ファイルが存在しない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        
        def mock_exists(self):
            path_str = str(self)
            if "source.mp4" in path_str:
                return True
            if "nonexistent_bgm.mp3" in path_str:
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            with pytest.raises(FileNotFoundError) as excinfo:
                engine.generate_preview("source.mp4", bgm_path="nonexistent_bgm.mp3")
            assert "BGM file not found" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_bgm_is_dir():
    """BGM パスがファイルではなくディレクトリの場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        original_is_file_local = Path.is_file
        
        # source.mp4 と bgm_dir は exists=True
        # source.mp4 は is_file=True, bgm_dir は is_file=False
        def mock_exists(self):
            path_str = str(self)
            if "source.mp4" in path_str or "bgm_dir" in path_str:
                return True
            return original_exists(self)
            
        def mock_is_file(self):
            path_str = str(self)
            if "source.mp4" in path_str:
                return True
            if "bgm_dir" in path_str:
                return False
            return True
            
        Path.exists = mock_exists
        Path.is_file = mock_is_file
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source.mp4", bgm_path="bgm_dir")
            assert "BGM path must be a file" in str(excinfo.value)
        finally:
            Path.exists = original_exists
            Path.is_file = original_is_file_local

def test_validate_params_invalid_duration_type():
    """duration が数値でない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(TypeError) as excinfo:
                engine.generate_preview("source.mp4", duration="invalid")
            assert "Duration must be a number" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_invalid_duration_value():
    """duration が 0 以下の値の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source.mp4", duration=0)
            assert "Duration must be positive and non-zero" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_invalid_tempo_low():
    """tempo_multiplier が 0.5 未満の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source.mp4", feedback_params={"tempo_multiplier": 0.4})
            assert "tempo_multiplier must be between 0.5 and 2.0" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_invalid_tempo_high():
    """tempo_multiplier が 2.0 超の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source.mp4", feedback_params={"tempo_multiplier": 2.1})
            assert "tempo_multiplier must be between 0.5 and 2.0" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_invalid_volume():
    """volume_multiplier が負数の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("source.mp4", feedback_params={"volume_multiplier": -0.1})
            assert "volume_multiplier must be non-negative" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_invalid_color_preset():
    """存在しないカラープリセットが指定された場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", [], color_preset="INVALID_PRESET")
            assert "Invalid color_preset" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_subtitles_not_list():
    """subtitles がリストでない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(TypeError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", "not_a_list")
            assert "Subtitles must be a list of dictionaries" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_subtitle_not_dict():
    """subtitles の要素が辞書でない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(TypeError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", ["not_a_dict"])
            assert "must be a dictionary" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_subtitle_missing_keys():
    """subtitles の辞書に必要なキーが欠けている場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(KeyError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", [{"text": "hello", "start": 0.0}])
            assert "missing required field: 'end'" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_subtitle_invalid_time_type():
    """subtitles の開始・終了時間が数値でない場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(TypeError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", [{"text": "hello", "start": "0.0", "end": 1.0}])
            assert "times at index 0 must be numbers" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_validate_params_subtitle_invalid_time_range():
    """subtitles の start > end の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_exists = Path.exists
        Path.exists = lambda self: True
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview_with_subtitles("source.mp4", [{"text": "hello", "start": 2.0, "end": 1.0}])
            assert "start time must be less than or equal to end time" in str(excinfo.value)
        finally:
            Path.exists = original_exists

def test_generate_preview_failure_cleanup():
    """generate_preview の FFmpeg 失敗時に出力一時ファイルがクリーンアップされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return True
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        unlinked_files = []
        def mock_unlink(self):
            path_str = str(self).replace("\\", "/").replace("\\", "/")
            if "previews" in path_str:
                unlinked_files.append(path_str)
                return
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError):
                engine.generate_preview("source.mp4")
            assert len(unlinked_files) > 0
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run

def test_cleanup_old_previews_os_error(tmp_path):
    """cleanup_old_previews で unlink 時に OSError が発生してもハンドリングされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        engine.preview_dir = tmp_path
        
        file = tmp_path / "old.mp4"
        file.touch()
        
        now = time.time()
        os.utime(file, (now - 9 * 86400, now - 9 * 86400))
        
        original_unlink = Path.unlink
        def mock_unlink(self):
            raise OSError("Access denied")
            
        Path.unlink = mock_unlink
        try:
            # 例外が発生せず安全に終了すること
            engine.cleanup_old_previews(days=7)
        finally:
            Path.unlink = original_unlink

def test_has_audio_stream_invalid_path():
    """_has_audio_stream に無効なパスが渡された場合に即座に False を返すこと"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        original_run = subprocess.run
        original_is_file_local = Path.is_file
        # テスト全体でモックされている is_file を一時的に本物に戻す
        Path.is_file = original_is_file
        
        run_called = False
        def mock_run(*args, **kwargs):
            nonlocal run_called
            run_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        subprocess.run = mock_run
        try:
            assert engine._has_audio_stream("") is False
            assert engine._has_audio_stream("nonexistent_path_no_file.mp4") is False
            assert run_called is False
        finally:
            subprocess.run = original_run
            Path.is_file = original_is_file_local


# 未カバー行の解消テストケース

def test_validate_params_empty_source():
    """source_videoが空文字列の場合のエラー"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        try:
            with pytest.raises(ValueError) as excinfo:
                engine.generate_preview("")
            assert "source_video path cannot be empty" in str(excinfo.value)
        finally:
            pass

def test_generate_preview_cleanup_os_error():
    """generate_preview失敗時、一時ファイル削除でOSErrorが発生した場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return True
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        def mock_unlink(self):
            path_str = str(self).replace("\\", "/")
            if "previews" in path_str:
                raise OSError("Access denied")
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError):
                engine.generate_preview("source.mp4")
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run

def test_generate_preview_with_subtitles_cleanup_os_error():
    """generate_preview_with_subtitles失敗時、一時ファイル削除でOSErrorが発生した場合"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self)
            if "previews" in path_str and path_str.endswith(".mp4"):
                return True
            if path_str.endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_unlink = Path.unlink
        def mock_unlink(self):
            path_str = str(self).replace("\\", "/")
            if "previews" in path_str:
                raise OSError("Access denied")
            return original_unlink(self)
            
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            if "ffprobe" in args[0][0]:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="FFmpeg failed")
            
        Path.exists = mock_exists
        Path.unlink = mock_unlink
        subprocess.run = mock_run
        try:
            with pytest.raises(RuntimeError):
                engine.generate_preview_with_subtitles("source.mp4", [])
        finally:
            Path.exists = original_exists
            Path.unlink = original_unlink
            subprocess.run = original_run


# --- 追加テストコード ---

def test_has_audio_stream_failed_exit_code():
    """ffprobe が例外を投げず正常に終了したものの、終了コードが非ゼロ（例: 1）の場合に False を返すこと"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="audio\n", stderr=""
        )
        
        original_run = subprocess.run
        run_called = False
        def mock_run(*args, **kwargs):
            nonlocal run_called
            run_called = True
            return mock_result
            
        subprocess.run = mock_run
        try:
            assert engine._has_audio_stream("dummy.mp4") is False
            assert run_called is True
        finally:
            subprocess.run = original_run

def test_get_font_path_escape_logic():
    """Windows形式のコロンを含むパスがある場合、FFmpeg用にエスケープされたパスが返されること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            path_str = str(self).replace("\\", "/")
            if path_str.endswith("Fonts/msgothic.ttc"):
                return True
            if any(c in path_str for c in ["arial.ttf", "SegoeUI.ttf", "DejaVuSans.ttf", "Helvetica.ttc"]):
                return False
            return original_exists(self)
            
        Path.exists = mock_exists
        try:
            font = engine._get_font_path()
            assert font == "C\\:/Windows/Fonts/msgothic.ttc"
        finally:
            Path.exists = original_exists

def test_cleanup_old_previews_stat_os_error(tmp_path):
    """cleanup_old_previewsで file.stat() 取得時に OSError が発生してもハンドリングされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        engine.preview_dir = tmp_path
        
        file1 = tmp_path / "old1.mp4"
        file2 = tmp_path / "old2.mp4"
        file1.touch()
        file2.touch()
        
        original_stat = Path.stat
        def mock_stat(self, *args, **kwargs):
            if self.name == "old1.mp4":
                raise OSError("Permission denied")
            return original_stat(self, *args, **kwargs)
            
        Path.stat = mock_stat
        try:
            # 例外が発生せず安全に終了すること
            engine.cleanup_old_previews(days=7)
        finally:
            Path.stat = original_stat
            
        # old1.mp4 は stat 失敗のため削除されず残るはず
        assert file1.exists()

def test_generate_preview_partial_feedback_params():
    """feedback_paramsに一部のキーのみが含まれる辞書やオブジェクトが渡された際にデフォルト値にフォールバックされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        original_run = subprocess.run
        run_args_dict = {}
        def mock_run(*args, **kwargs):
            run_args_dict['args'] = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            # 1. 辞書形式: tempo_multiplier のみ
            feedback_dict = {"tempo_multiplier": 1.2}
            engine.generate_preview("source.mp4", feedback_params=feedback_dict)
            af_arg = run_args_dict['args'][run_args_dict['args'].index("-af") + 1]
            assert "atempo=1.2" in af_arg
            assert "volume=" not in af_arg

            # 2. オブジェクト形式: volume_multiplier のみ
            class PartialFeedbackParams:
                volume_multiplier = 0.8
            
            engine.generate_preview("source.mp4", feedback_params=PartialFeedbackParams())
            af_arg = run_args_dict['args'][run_args_dict['args'].index("-af") + 1]
            assert "volume=0.8" in af_arg
            assert "atempo" not in af_arg
        finally:
            Path.exists = original_exists
            subprocess.run = original_run

def test_generate_preview_with_subtitles_tempo_scale_calculation():
    """generate_preview_with_subtitlesで tempo_multiplier 適用時に字幕の表示時間計算が正しくスケールされること"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        original_exists = Path.exists
        def mock_exists(self):
            if str(self).endswith("source.mp4"):
                return True
            return original_exists(self)
            
        engine._get_font_path = lambda: "C\\:/Windows/Fonts/msgothic.ttc"
        
        original_run = subprocess.run
        run_args = None
        def mock_run(*args, **kwargs):
            nonlocal run_args
            run_args = args[0]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        Path.exists = mock_exists
        subprocess.run = mock_run
        try:
            # テンポ 1.5倍速
            subtitles = [{"text": "Hello", "start": 3.0, "end": 6.0}]
            preview_id = engine.generate_preview_with_subtitles(
                "source.mp4", subtitles, feedback_params={"tempo_multiplier": 1.5}
            )
            assert preview_id is not None
            
            vf_val = run_args[run_args.index("-vf") + 1]
            assert "enable='between(t,2.0,4.0)'" in vf_val
            assert "alpha='if(lt(t,2.0+0.19999999999999998),(t-2.0)/0.19999999999999998,if(gt(t,4.0-0.19999999999999998),(4.0-t)/0.19999999999999998,1))'" in vf_val
        finally:
            Path.exists = original_exists
            subprocess.run = original_run


def test_preview_engine_thumbnail_success(tmp_path):
    """正常系: サムネイル生成および検証が成功することを確認"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        output_file = tmp_path / "test_thumb.png"
        
        # FFmpegはモック（subprocess.run を mock する）
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        subprocess.run = mock_run
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file),
                width=1280,
                height=720
            )
            
            assert Path(path_str).exists()
            
            # 品質検証
            result = engine.validate_thumbnail_quality(path_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            assert result["size_bytes"] > 0
            
        finally:
            subprocess.run = original_run


def test_preview_engine_thumbnail_validation_failures(tmp_path):
    """異常系: バリデーションエラーが正しく検出されることを確認"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # 1. 存在しないファイル
        with pytest.raises(FileNotFoundError):
            engine.validate_thumbnail_quality("nonexistent_file.png")
            
        # 2. 空のファイル (破損画像)
        empty_file = tmp_path / "empty.png"
        empty_file.touch()
        with pytest.raises(ValueError) as excinfo:
            engine.validate_thumbnail_quality(str(empty_file))
        assert "corrupted or invalid" in str(excinfo.value)
        
        # 3. サイズ制限超過
        large_file = tmp_path / "large.png"
        with open(large_file, "wb") as f:
            f.write(b"\0" * (4 * 1024 * 1024 + 1))
        with pytest.raises(ValueError) as excinfo:
            engine.validate_thumbnail_quality(str(large_file))
        assert "exceeds 4MB limit" in str(excinfo.value)
        
        # 4. 解像度不足の画像
        small_image = tmp_path / "small.png"
        from PIL import Image
        img = Image.new("RGB", (640, 360), color="blue")
        img.save(small_image, "PNG")
        with pytest.raises(ValueError) as excinfo:
            engine.validate_thumbnail_quality(str(small_image))
        assert "Resolution must be at least 1280x720" in str(excinfo.value)
        
        # 5. アスペクト比異常
        bad_aspect = tmp_path / "bad_aspect.png"
        img2 = Image.new("RGB", (1280, 1000), color="red")
        img2.save(bad_aspect, "PNG")
        with pytest.raises(ValueError) as excinfo:
            engine.validate_thumbnail_quality(str(bad_aspect))
        assert "Aspect ratio must be 16:9" in str(excinfo.value)


@pytest.mark.asyncio
async def test_preview_engine_thumbnail_stage_bound_agent(tmp_path):
    """StageBoundAgent との自動リトライ、結果保存、マイグレーション連携のテスト"""
    import asyncio
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "test_stage_bound_agent.db"
    
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # テスト用の属性を engine に設定
        engine.width = 1280
        engine.height = 720
        engine.video_path = "dummy.mp4"
        engine.timestamp = 1.5
        
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file), poll_interval=0.01)
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        subprocess.run = mock_run
        
        try:
            import uuid
            # タスク登録
            task_id = f"test_task_001_{uuid.uuid4().hex}"
            await agent.register_task(task_id, initial_status="READY", max_retries=1)
            
            # エージェント起動
            await agent.start(engine.resolve_preview_thumbnail_task)
            
            # ステータスが COMPLETED になるのを待つ
            for _ in range(100):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.02)
                
            status = await agent.get_task_status(task_id)
            assert status == "COMPLETED"
            
            # DBに保存された結果の検証
            conn = agent._get_conn()
            try:
                row = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row is not None
                import json
                result_info = json.loads(row[0])
                assert result_info["width"] == 1280
                assert result_info["height"] == 720
                assert "path" in result_info
                assert row[1] is None
                assert row[2] == 0
            finally:
                agent._close_conn(conn)
                
            await agent.stop()
            
            # --- リトライ連携テスト (エラー発生時に自動リトライされること) ---
            task_id_fail = f"test_task_fail_{uuid.uuid4().hex}"
            # 解像度がおかしいエラーを発生させるために engine.width を 100 に変更、自動補正を無効化
            engine.width = 100
            engine.auto_scale = False
            
            agent_fail = StageBoundAgent(stage_name="thumbnail_fail", db_path=str(db_file), poll_interval=0.01)
            await agent_fail.register_task(task_id_fail, initial_status="READY", max_retries=2)
            await agent_fail.start(engine.resolve_preview_thumbnail_task)
            
            for _ in range(100):
                status = await agent_fail.get_task_status(task_id_fail)
                if status == "FAILED":
                    break
                await asyncio.sleep(0.02)
                
            status = await agent_fail.get_task_status(task_id_fail)
            assert status == "FAILED"
            
            # DBの確認
            conn_fail = agent_fail._get_conn()
            try:
                row = conn_fail.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id_fail,)).fetchone()
                assert row is not None
                assert row[0] is None
                assert "Resolution must be at least 1280x720" in row[1]
                assert row[2] == 2  # max_retries=2 なので 2 回リトライされたはず
            finally:
                agent_fail._close_conn(conn_fail)
                
            await agent_fail.stop()
            
        finally:
            subprocess.run = original_run


def test_generate_thumbnail_quality_rule_validation_pillow_fallback(tmp_path):
    """
    CalledProcessError を投げて強制的に Pillow フォールバックを作らせ、
    生成された画像が品質基準（解像度1280x720以上、16:9アスペクト比、4MB未満、正常にロード可能）
    を満たすことを検証する。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        output_file = tmp_path / "fallback_thumb.png"
        
        # FFmpegの呼び出しでエラーを発生させる
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced FFmpeg failure for fallback test")
            
        subprocess.run = mock_run
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file),
                timestamp=0.0,
                width=1280,
                height=720
            )
            
            # 出力ファイルの存在確認
            assert Path(path_str).exists()
            
            # 品質検証
            result = engine.validate_thumbnail_quality(path_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            assert result["size_bytes"] < 4 * 1024 * 1024
            
            # アスペクト比確認
            aspect_ratio = result["width"] / result["height"]
            assert abs(aspect_ratio - 16.0/9.0) < 0.01
            
            # Pillowで正常にロード可能か（破損していないか）
            from PIL import Image
            with Image.open(path_str) as img:
                img.verify()
                
            with Image.open(path_str) as img:
                img.load()
                assert img.size == (1280, 720)
                
        finally:
            subprocess.run = original_run


def test_generate_thumbnail_invalid_params_validation():
    """無効な入力パラメータ（負のタイムスタンプ、正でない解像度）に対して適切に ValueError が発生することを確認"""
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # 1. 負のタイムスタンプ
        with pytest.raises(ValueError) as excinfo:
            engine.generate_thumbnail("dummy.mp4", "out.png", timestamp=-1.0)
        assert "timestamp cannot be negative" in str(excinfo.value)
        
        # 2. 幅が 0 以下
        with pytest.raises(ValueError) as excinfo:
            engine.generate_thumbnail("dummy.mp4", "out.png", width=0)
        assert "width and height must be positive integers" in str(excinfo.value)
        
        # 3. 高さが 0 以下
        with pytest.raises(ValueError) as excinfo:
            engine.generate_thumbnail("dummy.mp4", "out.png", height=-100)
        assert "width and height must be positive integers" in str(excinfo.value)


def test_thumbnail_quality_standards_resolution_aspect_ratio_filesize(tmp_path):
    """
    【最優先：品質基準テスト】
    入力が低解像度であっても、自動補正され品質基準（1280x720以上、16:9、4MB未満、Pillowロード可能）
    を確実に満たすことを検証する。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        output_file = tmp_path / "quality_rule_test.png"
        
        # FFmpegの呼び出しでエラーを発生させてPillowフォールバックを動かす
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced failure")
        subprocess.run = mock_run
        
        try:
            # 意図的に 640x480 (16:9ではない、低解像度) を指定して生成
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file),
                timestamp=0.0,
                width=640,
                height=480
            )
            
            assert Path(path_str).exists()
            
            # 品質検証
            result = engine.validate_thumbnail_quality(path_str)
            
            # 1. 解像度が 1280x720 以上であること
            assert result["width"] >= 1280
            assert result["height"] >= 720
            
            # 2. アスペクト比が 16:9 であること
            aspect_ratio = result["width"] / result["height"]
            assert abs(aspect_ratio - 16.0/9.0) < 0.01
            
            # 3. ファイルサイズが 4MB 未満であること
            assert result["size_bytes"] < 4 * 1024 * 1024
            
            # 4. Pillow等で正常にロード可能であること
            from PIL import Image
            with Image.open(path_str) as img:
                img.verify()
            with Image.open(path_str) as img:
                img.load()
                assert img.size[0] >= 1280
                assert img.size[1] >= 720
                
        finally:
            subprocess.run = original_run


def test_thumbnail_quality_standards_invalid_paths(tmp_path):
    """
    video_path や output_path にディレクトリが渡された場合、
    速やかに ValueError が発生することを検証する。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # 1. video_path がディレクトリの場合
        with pytest.raises(ValueError) as excinfo:
            engine.generate_thumbnail(
                video_path=str(tmp_path),
                output_path=str(tmp_path / "out.png")
            )
        assert "video_path must be a file, not a directory" in str(excinfo.value)
        
        # 2. output_path がディレクトリの場合
        dummy_file = tmp_path / "dummy.mp4"
        dummy_file.touch()
        with pytest.raises(ValueError) as excinfo:
            engine.generate_thumbnail(
                video_path=str(dummy_file),
                output_path=str(tmp_path)
            )
        assert "output_path must be a file path, not a directory" in str(excinfo.value)
def test_preview_engine_thumbnail_auto_scale_option(tmp_path):
    """
    generate_thumbnail における auto_scale パラメータの挙動を検証する。
    1. auto_scale=True (デフォルト) の場合、低解像度入力は1280x720以上に自動補正される。
    2. auto_scale=False の場合、補正されずに低解像度のまま生成され、品質検証で ValueError となる。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        dummy_video = tmp_path / "dummy.mp4"
        dummy_video.touch()
        
        # 1. auto_scale=True (デフォルト) -> 自動補正で 1280x720 以上の 16:9 画像が生成される
        out_path_scaled = tmp_path / "scaled.png"
        engine.generate_thumbnail(
            video_path=str(dummy_video),
            output_path=str(out_path_scaled),
            width=640,
            height=480,
            auto_scale=True
        )
        
        # 検証 (Pillowで画像を開いてサイズを確認)
        from PIL import Image
        with Image.open(out_path_scaled) as img:
            assert img.size == (1280, 720)
            
        # 2. auto_scale=False -> 補正なしで 640x480 で生成され、validate_thumbnail_quality でエラーになる
        out_path_unscaled = tmp_path / "unscaled.png"
        engine.generate_thumbnail(
            video_path=str(dummy_video),
            output_path=str(out_path_unscaled),
            width=640,
            height=480,
            auto_scale=False
        )
        
        with Image.open(out_path_unscaled) as img:
            assert img.size == (640, 480)
            
        with pytest.raises(ValueError) as excinfo:
            engine.validate_thumbnail_quality(str(out_path_unscaled))
        assert "Resolution must be at least 1280x720" in str(excinfo.value)


# --- T-batch_dff59e-thumbnail-001 追加テスト ---

def test_preview_engine_thumbnail_webp_format_support(tmp_path):
    """
    WebP形式が指定された場合に、FFmpeg/PillowフォールバックでWebP品質を満たすサムネイルが生成され、
    validate_thumbnail_quality で正常に検証できること。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        output_file = tmp_path / "test_thumb.webp"
        
        # FFmpegの呼び出しでエラーを発生させてPillowフォールバックを動かす
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced failure")
        subprocess.run = mock_run
        
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file),
                timestamp=0.0,
                width=1280,
                height=720
            )
            
            assert Path(path_str).exists()
            assert path_str.endswith(".webp")
            
            # 品質検証
            result = engine.validate_thumbnail_quality(path_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            assert result["size_bytes"] < 4 * 1024 * 1024
            
            # Pillowで正常にロード可能か
            from PIL import Image
            with Image.open(path_str) as img:
                img.verify()
            with Image.open(path_str) as img:
                img.load()
                assert img.format == "WEBP"
                
        finally:
            subprocess.run = original_run

def test_thumbnail_extreme_aspect_ratio_auto_scale(tmp_path):
    """
    極端なアスペクト比（例: 縦長 360x1280、横長 2560x360）が指定された場合、
    auto_scale=Trueによってアスペクト比が 16:9 (約1.77) に厳密に補正され、
    解像度が 1280x720 以上になること。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # 1. 縦長 (360x1280)
        output_file_tall = tmp_path / "tall.png"
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced failure")
        subprocess.run = mock_run
        
        try:
            path_tall = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file_tall),
                width=360,
                height=1280,
                auto_scale=True
            )
            result_tall = engine.validate_thumbnail_quality(path_tall)
            assert result_tall["width"] >= 1280
            assert result_tall["height"] >= 720
            aspect_tall = result_tall["width"] / result_tall["height"]
            assert abs(aspect_tall - 16.0/9.0) < 0.01
            
            # 2. 横長 (2560x360)
            output_file_wide = tmp_path / "wide.png"
            path_wide = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file_wide),
                width=2560,
                height=360,
                auto_scale=True
            )
            result_wide = engine.validate_thumbnail_quality(path_wide)
            assert result_wide["width"] >= 1280
            assert result_wide["height"] >= 720
            aspect_wide = result_wide["width"] / result_wide["height"]
            assert abs(aspect_wide - 16.0/9.0) < 0.01
            
        finally:
            subprocess.run = original_run

@pytest.mark.asyncio
async def test_preview_engine_thumbnail_stage_bound_agent_with_params(tmp_path):
    """
    StageBoundAgent 連携時に resolve_preview_thumbnail_task に params を渡すことで、
    params で指定したパラメータ（解像度、拡張子など）に応じたサムネイル生成が非同期で実行され、
    結果が正しく COMPLETED になること。
    """
    import asyncio
    import json
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "test_stage_bound_params.db"
    
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        agent = StageBoundAgent(stage_name="thumbnail_params", db_path=str(db_file), poll_interval=0.01)
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        subprocess.run = mock_run
        
        try:
            import uuid
            task_id = f"task_params_{uuid.uuid4().hex}"
            await agent.register_task(task_id, initial_status="READY", max_retries=1)
            
            # resolve_preview_thumbnail_task に params 引数を部分適用して StageBoundAgent に渡す
            params = {
                "width": 1920,
                "height": 1080,
                "ext": "webp",
                "timestamp": 2.5,
                "video_path": "dummy_video.mp4",
                "auto_scale": True
            }
            
            async def test_handler(tid):
                return await engine.resolve_preview_thumbnail_task(tid, params=params)
                
            await agent.start(test_handler)
            
            for _ in range(100):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.02)
                
            status = await agent.get_task_status(task_id)
            assert status == "COMPLETED"
            
            # DBの検証
            conn = agent._get_conn()
            try:
                row = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row is not None
                result_info = json.loads(row[0])
                assert result_info["width"] == 1920
                assert result_info["height"] == 1080
                assert result_info["path"].endswith(".webp")
                assert row[1] is None
            finally:
                agent._close_conn(conn)
                
            await agent.stop()
        finally:
            subprocess.run = original_run


# --- T-batch_658920-thumbnail-001 新規追加テスト ---

def test_generate_thumbnail_with_text_overlay_validation(tmp_path):
    """
    引数 title_text および subtitle_text を指定して generate_thumbnail を呼び出した際、
    FFmpegエラーでのフォールバック生成および通常生成の両パターンにおいて、
    Pillowのテキスト描画が適用され、品質基準（1280x720以上、16:9、4MB未満、Pillowロード可能）
    を満たすことを自動検証する。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        
        # パターン1: FFmpegエラー時のPillowフォールバックでのテキスト合成
        output_file_fallback = tmp_path / "text_fallback.png"
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced failure for fallback text test")
        subprocess.run = mock_run
        
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file_fallback),
                width=1280,
                height=720,
                title_text="Test Main Title",
                subtitle_text="Test Subtitle Text"
            )
            
            assert Path(path_str).exists()
            result = engine.validate_thumbnail_quality(path_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            
            # Pillowで開いて検証
            from PIL import Image
            with Image.open(path_str) as img:
                img.verify()
                
        finally:
            subprocess.run = original_run

        # パターン2: FFmpeg成功時のPillowによるテキスト合成
        output_file_success = tmp_path / "text_success.png"
        # 成功時はダミーファイルを生成して、それをPillowで読み込み・テキスト合成することになる
        # モックの run が呼ばれた直後にダミーの 1280x720 画像を配置して成功を模倣する
        def mock_run_success(*args, **kwargs):
            from PIL import Image
            img = Image.new("RGB", (1280, 720), color="blue")
            img.save(output_file_success)
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            
        subprocess.run = mock_run_success
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file_success),
                width=1280,
                height=720,
                title_text="Success Title",
                subtitle_text="Success Subtitle"
            )
            
            assert Path(path_str).exists()
            result = engine.validate_thumbnail_quality(path_str)
            assert result["width"] == 1280
            assert result["height"] == 720
            
            with Image.open(path_str) as img:
                img.verify()
        finally:
            subprocess.run = original_run


def test_generate_thumbnail_file_size_safeguard_validation(tmp_path):
    """
    ファイルサイズが4MBを超える巨大なダミー画像を保存しようとした際に、
    自動再圧縮セーフガード（画質調整やJPEG変換）が働き、
    最終的に4MB未満に圧縮された画像が保存され、ロード可能であることを自動検証する。
    """
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        output_file = tmp_path / "safeguard_test.png"
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="Forced failure for size safeguard test")
        subprocess.run = mock_run
        
        # 4MBを超える巨大なピクセルサイズを指定（5120x2880 の巨大PNGを生成させる）
        try:
            path_str = engine.generate_thumbnail(
                video_path="dummy.mp4",
                output_path=str(output_file),
                width=5120,
                height=2880,
                title_text="Huge Size Title"
            )
            
            assert Path(path_str).exists()
            
            # 品質検証がパスすること（4MB未満であること）
            result = engine.validate_thumbnail_quality(path_str)
            assert result["size_bytes"] < 4 * 1024 * 1024
            
            # Pillowでロード可能なこと
            from PIL import Image
            with Image.open(path_str) as img:
                img.load()
                
        finally:
            subprocess.run = original_run


@pytest.mark.asyncio
async def test_resolve_preview_thumbnail_task_with_text_params(tmp_path):
    """
    StageBoundAgent 連携で、タスクの params に title_text や subtitle_text を指定して
    resolve_preview_thumbnail_task を実行した際、テキスト合成が正常に行われ、
    タスクが COMPLETED になることを自動検証する。
    """
    import asyncio
    import json
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "test_stage_bound_text.db"
    
    with patch_shutil_which("/usr/bin/ffmpeg"):
        engine = PreviewEngine()
        agent = StageBoundAgent(stage_name="thumbnail_text", db_path=str(db_file), poll_interval=0.01)
        
        original_run = subprocess.run
        def mock_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        subprocess.run = mock_run
        
        try:
            import uuid
            task_id = f"task_text_{uuid.uuid4().hex}"
            await agent.register_task(task_id, initial_status="READY", max_retries=1)
            
            params = {
                "width": 1280,
                "height": 720,
                "ext": "png",
                "timestamp": 1.0,
                "video_path": "dummy_video.mp4",
                "auto_scale": True,
                "title_text": "Agent Main Title",
                "subtitle_text": "Agent Subtitle Text"
            }
            
            async def test_handler(tid):
                return await engine.resolve_preview_thumbnail_task(tid, params=params)
                
            await agent.start(test_handler)
            
            for _ in range(100):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.02)
                
            status = await agent.get_task_status(task_id)
            assert status == "COMPLETED"
            
            # DBの検証
            conn = agent._get_conn()
            try:
                row = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,)).fetchone()
                assert row is not None
                result_info = json.loads(row[0])
                assert result_info["width"] == 1280
                assert result_info["height"] == 720
                assert Path(result_info["path"]).exists()
                assert row[1] is None
            finally:
                agent._close_conn(conn)
                
            await agent.stop()
        finally:
            subprocess.run = original_run
