import pytest
from unittest.mock import patch
import subprocess
from pathlib import Path
import sys

# バックエンドルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from video_editor_engine import FFmpegEditor

def test_run_command_os_error():
    """OSError が発生した際に run_command が False とエラー内容を返すこと"""
    editor = FFmpegEditor()
    editor.ffmpeg_path = "dummy_ffmpeg"
    
    with patch("subprocess.run", side_effect=OSError("OS error mock")):
        success, msg = editor.run_command(["args"])
        assert not success
        assert "OS error mock" in msg

def test_run_command_value_error():
    """ValueError が発生した際に run_command が False とエラー内容を返すこと"""
    editor = FFmpegEditor()
    editor.ffmpeg_path = "dummy_ffmpeg"
    
    with patch("subprocess.run", side_effect=ValueError("Value error mock")):
        success, msg = editor.run_command(["args"])
        assert not success
        assert "Value error mock" in msg

def test_run_command_other_exceptions_propagate():
    """OSError/ValueError 以外の例外が発生した際はキャッチせずに伝播すること（修正後の挙動を保証）"""
    editor = FFmpegEditor()
    editor.ffmpeg_path = "dummy_ffmpeg"
    
    with patch("subprocess.run", side_effect=RuntimeError("Runtime error mock")):
        with pytest.raises(RuntimeError) as exc_info:
            editor.run_command(["args"])
        assert "Runtime error mock" in str(exc_info.value)
