"""
backend/rebuild_with_s04_telop.py に対するテスト
"""

import sys
import os
import runpy
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from PIL import Image

# sys.path に backend ディレクトリを追加して、インポートできるようにする
backend_dir = str(Path(__file__).parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import rebuild_with_s04_telop

project_root = Path(backend_dir).parent

def test_create_scene04_telop_success():
    """create_scene04_telop が正常フォントロードで正常に動作することを確認"""
    mock_font = MagicMock()
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font) as mock_truetype,          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text") as mock_text,          patch("PIL.Image.Image.save") as mock_save:
        
        result = rebuild_with_s04_telop.create_scene04_telop()
        
        expected_path = project_root / "backend" / "branding" / "scene04_telop.png"
        assert result == expected_path
        
        # 最初のYuGothBが呼ばれることを確認
        mock_truetype.assert_called_once_with(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        mock_text.assert_called_once()
        mock_save.assert_called_once()


def test_create_scene04_telop_font_fallback():
    """create_scene04_telop がフォントのロードに失敗し、msgothicにフォールバックすることを確認"""
    mock_font = MagicMock()
    
    # 最初の呼び出しで例外を投げ、2回目の呼び出しでフォントオブジェクトを返す
    def side_effect(font_path, size):
        if "YuGothB" in font_path:
            raise OSError("Font load failed")
        return mock_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype,          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text") as mock_text,          patch("PIL.Image.Image.save") as mock_save:
        
        result = rebuild_with_s04_telop.create_scene04_telop()
        
        expected_path = project_root / "backend" / "branding" / "scene04_telop.png"
        assert result == expected_path
        
        # 2回呼ばれることを確認
        assert mock_truetype.call_count == 2
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\msgothic.ttc", 20)
        
        mock_text.assert_called_once()
        mock_save.assert_called_once()


def test_rebuild_and_add_telop_success():
    """rebuild_and_add_telop が正常終了することを確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    mock_completed_overlay = MagicMock()
    mock_completed_overlay.returncode = 0
    
    mock_completed_probe = MagicMock()
    mock_completed_probe.returncode = 0
    mock_completed_probe.stdout = "3600.0\n"
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            return mock_completed_overlay
        elif "ffprobe" in cmd_str:
            return mock_completed_probe
        return MagicMock(returncode=0)

    # Path.exists の挙動をモック
    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        if "soul_narrative_TELOP_UNIFIED.mp4" in str(self):
            return True
        return False
        
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024  # 100MB

    with patch("subprocess.run", side_effect=mock_run) as mock_subrun,          patch("pathlib.Path.exists", mock_exists),          patch("pathlib.Path.stat", return_value=mock_stat),          patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        
        expected_output = str(project_root / "soul_narrative_TELOP_UNIFIED.mp4")
        assert result == expected_output
        
        # 3回FFmpeg / FFprobeコマンドが呼ばれることを確認
        assert mock_subrun.call_count == 3


def test_rebuild_and_add_telop_concat_fail():
    """再結合（concat）に失敗したケース"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 1
    mock_completed_concat.stderr = "Concatenation error message"
    
    with patch("subprocess.run", return_value=mock_completed_concat) as mock_subrun,          patch("pathlib.Path.exists", return_value=False):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None


def test_rebuild_and_add_telop_overlay_fail():
    """テロップ追加（overlay）に失敗したケース"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    mock_completed_overlay = MagicMock()
    mock_completed_overlay.returncode = 1
    mock_completed_overlay.stderr = "Overlay error message"
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            return mock_completed_overlay
        return MagicMock(returncode=0)
        
    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        return False

    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024  # 100MB

    with patch("subprocess.run", side_effect=mock_run) as mock_subrun,          patch("pathlib.Path.exists", mock_exists),          patch("pathlib.Path.stat", return_value=mock_stat),          patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None


def test_main_block_success():
    """__main__ ブロックの正常系動作を確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    mock_completed_overlay = MagicMock()
    mock_completed_overlay.returncode = 0
    
    mock_completed_probe = MagicMock()
    mock_completed_probe.returncode = 0
    mock_completed_probe.stdout = "3600.0\n"
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            return mock_completed_overlay
        elif "ffprobe" in cmd_str:
            return mock_completed_probe
        return MagicMock(returncode=0)

    def mock_exists(self):
        return True
        
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024  # 100MB

    mock_font = MagicMock()

    with patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.exists", mock_exists),          patch("pathlib.Path.stat", return_value=mock_stat),          patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text"),          patch("PIL.Image.Image.save"):
         
        module_path = os.path.join(os.path.dirname(rebuild_with_s04_telop.__file__), "rebuild_with_s04_telop.py")
        runpy.run_path(module_path, run_name="__main__")


def test_main_block_fail():
    """__main__ ブロックの異常系動作を確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 1  # 失敗させる
    mock_completed_concat.stderr = "Error message"
    
    def mock_run(cmd, *args, **kwargs):
        return mock_completed_concat

    def mock_exists(self):
        return False
        
    with patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.exists", mock_exists):
         
        module_path = os.path.join(os.path.dirname(rebuild_with_s04_telop.__file__), "rebuild_with_s04_telop.py")
        runpy.run_path(module_path, run_name="__main__")


def test_create_scene04_telop_all_fonts_fail():
    """YuGothBもmsgothicもロードに失敗した場合、デフォルトフォントが使用されることを確認"""
    mock_default_font = MagicMock()
    
    def side_effect(font_path, size):
        raise OSError("Font load failed")

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype,          patch("PIL.ImageFont.load_default", return_value=mock_default_font) as mock_load_default,          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text") as mock_text,          patch("PIL.Image.Image.save") as mock_save:
        
        result = rebuild_with_s04_telop.create_scene04_telop()
        
        expected_path = project_root / "backend" / "branding" / "scene04_telop.png"
        assert result == expected_path
        
        # 2回のフォントロード試行と、最終のデフォルトフォント読み込みを確認
        assert mock_truetype.call_count == 2
        mock_load_default.assert_called_once()
        mock_text.assert_called_once()
        mock_save.assert_called_once()


def test_rebuild_and_add_telop_concat_exception():
    """再結合（concat）時に subprocess が例外を投げた場合の処理を確認"""
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Concat subprocess error")),          patch("pathlib.Path.exists", return_value=False):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None


def test_rebuild_and_add_telop_overlay_exception():
    """テロップ追加（overlay）時に subprocess が例外を投げた場合の処理を確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            raise subprocess.SubprocessError("Overlay subprocess error")
        return MagicMock(returncode=0)
        
    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        return False

    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024  # 100MB

    with patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.exists", mock_exists),          patch("pathlib.Path.stat", return_value=mock_stat),          patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None


def test_rebuild_and_add_telop_probe_exception():
    """ffprobeでのduration取得時に例外が発生しても、正常終了してパスを返すことを確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    mock_completed_overlay = MagicMock()
    mock_completed_overlay.returncode = 0
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            return mock_completed_overlay
        elif "ffprobe" in cmd_str:
            raise subprocess.SubprocessError("Probe subprocess error")
        return MagicMock(returncode=0)

    # Path.exists の挙動をモック
    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        if "soul_narrative_TELOP_UNIFIED.mp4" in str(self):
            return True
        return False
        
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024  # 100MB

    with patch("subprocess.run", side_effect=mock_run) as mock_subrun, \
         patch("pathlib.Path.exists", mock_exists), \
         patch("pathlib.Path.stat", return_value=mock_stat), \
         patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        
        expected_output = str(project_root / "soul_narrative_TELOP_UNIFIED.mp4")
        assert result == expected_output


def test_rebuild_and_add_telop_probe_value_error():
    """ffprobeの出力がパース不能な（ValueErrorになる）場合でも正常終了してパスを返すことを確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    mock_completed_overlay = MagicMock()
    mock_completed_overlay.returncode = 0
    
    mock_completed_probe = MagicMock()
    mock_completed_probe.returncode = 0
    mock_completed_probe.stdout = "not_a_float_value\n"
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            return mock_completed_overlay
        elif "ffprobe" in cmd_str:
            return mock_completed_probe
        return MagicMock(returncode=0)

    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        if "soul_narrative_TELOP_UNIFIED.mp4" in str(self):
            return True
        return False
        
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024

    with patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.exists", mock_exists), \
         patch("pathlib.Path.stat", return_value=mock_stat), \
         patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        
        expected_output = str(project_root / "soul_narrative_TELOP_UNIFIED.mp4")
        assert result == expected_output


def test_rebuild_and_add_telop_concat_timeout():
    """再結合（concat）時に TimeoutExpired 例外が発生した場合の挙動を確認"""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300)), \
         patch("pathlib.Path.exists", return_value=False):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None


def test_rebuild_and_add_telop_overlay_timeout():
    """テロップ追加（overlay）時に TimeoutExpired 例外が発生した場合の挙動を確認"""
    mock_completed_concat = MagicMock()
    mock_completed_concat.returncode = 0
    
    def mock_run(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd)
        if "concat" in cmd_str:
            return mock_completed_concat
        elif "overlay" in cmd_str:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=600)
        return MagicMock(returncode=0)
        
    def mock_exists(self):
        if "soul_narrative_REBUILT.mp4" in str(self):
            return True
        return False

    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024 * 1024

    with patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.exists", mock_exists), \
         patch("pathlib.Path.stat", return_value=mock_stat), \
         patch("rebuild_with_s04_telop.create_scene04_telop", return_value=Path("dummy_telop.png")):
         
        result = rebuild_with_s04_telop.rebuild_and_add_telop()
        assert result is None
