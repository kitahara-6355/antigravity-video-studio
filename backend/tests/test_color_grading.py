# -*- coding: utf-8 -*-
import pytest
import os
import sys
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from color_grading import ColorGrading

@pytest.fixture
def mock_ffmpeg(tmp_path):
    return str(tmp_path / "ffmpeg")

def test_init_ffmpeg_from_which(mock_ffmpeg):
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        assert engine.ffmpeg == mock_ffmpeg

def test_init_ffmpeg_from_local_bin():
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        assert "ffmpeg.exe" in engine.ffmpeg

def test_init_ffmpeg_not_found():
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        assert engine.ffmpeg is None
        
        with pytest.raises(RuntimeError) as exc:
            engine.apply_preset("dummy.mp4", "cinematic")
        assert "FFmpeg not found" in str(exc.value)

def test_apply_preset_success(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls, \
         patch("color_grading.PreviewReportGenerator") as mock_gen_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.output_dir = tmp_path / "preview"
        mock_preview_cls.return_value = mock_preview
        
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen
        
        engine = ColorGrading()
        out_path = engine.apply_preset(str(video), "cinematic")
        
        assert out_path is not None
        assert "graded_videos" in out_path
        assert "graded_cinematic" in out_path
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "-vf" in cmd
        assert "eq=contrast=1.2" in cmd[cmd.index("-vf")+1]
        mock_preview.snapshot_step.assert_called_once()
        mock_gen.generate_from_session_dir.assert_called_once()

def test_apply_preset_none(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        engine = ColorGrading()
        out_path = engine.apply_preset(str(video), "none")
        
        assert out_path is not None
        assert "graded_videos" in out_path
        assert "graded_none" in out_path
        cmd = mock_run.call_args[0][0]
        assert "-vf" not in cmd
        assert "copy" in cmd

def test_apply_preset_file_not_found(mock_ffmpeg):
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        with pytest.raises(FileNotFoundError):
            engine.apply_preset("nonexistent.mp4")

def test_apply_preset_unknown(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        with pytest.raises(ValueError):
            engine.apply_preset(str(video), "unknown_preset")

def test_apply_preset_ffmpeg_error(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"FFmpeg error output")):
        engine = ColorGrading()
        with pytest.raises(RuntimeError) as exc:
            engine.apply_preset(str(video), "cinematic")
        assert "Color grading failed" in str(exc.value)

def test_apply_preset_preview_exception(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = ValueError("Preview Generation Error")
        mock_preview_cls.return_value = mock_preview
        
        engine = ColorGrading()
        out_path = engine.apply_preset(str(video), "cinematic")
        assert out_path is not None

def test_apply_preset_preview_unexpected_exception(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = Exception("Unexpected Error")
        mock_preview_cls.return_value = mock_preview
        
        engine = ColorGrading()
        out_path = engine.apply_preset(str(video), "cinematic")
        assert out_path is not None

def test_apply_custom_lut_success(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    lut = tmp_path / "preset.cube"
    lut.write_text("dummy lut", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls, \
         patch("color_grading.PreviewReportGenerator") as mock_gen_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.output_dir = tmp_path / "preview"
        mock_preview_cls.return_value = mock_preview
        
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen
        
        engine = ColorGrading()
        out_path = engine.apply_custom_lut(str(video), str(lut))
        
        assert out_path is not None
        assert "graded_videos" in out_path
        assert "lut_applied" in out_path
        cmd = mock_run.call_args[0][0]
        from color_grading import _escape_filter_path
        assert f"lut3d={_escape_filter_path(str(lut))}" in cmd[cmd.index("-vf")+1]
        
        # Progressive Preview の呼び出し検証 (憲法 9.1)
        mock_preview.snapshot_step.assert_called_once()
        mock_gen.generate_from_session_dir.assert_called_once()

def test_apply_custom_lut_file_not_found(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    lut = tmp_path / "preset.cube"
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        with pytest.raises(FileNotFoundError):
            engine.apply_custom_lut("nonexistent.mp4", str(lut))
        with pytest.raises(FileNotFoundError):
            engine.apply_custom_lut(str(video), "nonexistent.cube")

def test_apply_custom_lut_ffmpeg_error(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    lut = tmp_path / "preset.cube"
    lut.write_text("dummy lut", encoding="utf-8")
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"LUT error output")):
        engine = ColorGrading()
        with pytest.raises(RuntimeError) as exc:
            engine.apply_custom_lut(str(video), str(lut))
        assert "LUT application failed" in str(exc.value)

def test_apply_preset_non_utf8_ffmpeg_error(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    # CP932でデコードエラーが起きるような非ASCIIバイト列
    non_utf8_stderr = b"\x82\xa0\x82\xa2\x82\xa4" # 「あいう」(CP932)
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=non_utf8_stderr)):
        engine = ColorGrading()
        with pytest.raises(RuntimeError) as exc:
            engine.apply_preset(str(video), "cinematic")
        assert "Color grading failed" in str(exc.value)

def test_apply_custom_lut_non_utf8_ffmpeg_error(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    lut = tmp_path / "preset.cube"
    lut.write_text("dummy lut", encoding="utf-8")
    
    # CP932でデコードエラーが起きるような非ASCIIバイト列
    non_utf8_stderr = b"\x82\xa0\x82\xa2\x82\xa4" # 「あいう」(CP932)
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=non_utf8_stderr)):
        engine = ColorGrading()
        with pytest.raises(RuntimeError) as exc:
            engine.apply_custom_lut(str(video), str(lut))
        assert "LUT application failed" in str(exc.value)

def test_apply_lut_success(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    out = tmp_path / "output.mp4"
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls, \
         patch("color_grading.PreviewReportGenerator") as mock_gen_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.output_dir = tmp_path / "preview"
        mock_preview_cls.return_value = mock_preview
        
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen
        
        engine = ColorGrading()
        out_path = engine.apply_lut(str(video), str(out), "cinematic")
        
        assert out_path == str(out)
        mock_run.assert_called_once()
        mock_preview.snapshot_step.assert_called_once()
        mock_gen.generate_from_session_dir.assert_called_once()

def test_apply_lut_preview_exception(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    out = tmp_path / "output.mp4"
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = ValueError("Preview Generation Error")
        mock_preview_cls.return_value = mock_preview
        
        engine = ColorGrading()
        out_path = engine.apply_lut(str(video), str(out), "cinematic")
        assert out_path == str(out)

def test_apply_lut_preview_unexpected_exception(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    out = tmp_path / "output.mp4"
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = Exception("Unexpected Preview Error")
        mock_preview_cls.return_value = mock_preview
        
        engine = ColorGrading()
        out_path = engine.apply_lut(str(video), str(out), "cinematic")
        assert out_path == str(out)


def test_escape_filter_path():
    from color_grading import _escape_filter_path
    windows_path = r"C:\Users\PC_User\Documents\preset.cube"
    escaped = _escape_filter_path(windows_path)
    assert "C\\:/Users/PC_User/Documents/preset.cube" in escaped

def test_directories_are_absolute():
    with patch("shutil.which", return_value="ffmpeg"), \
         patch("pathlib.Path.mkdir"):
        engine = ColorGrading()
        assert Path(engine.lut_dir).is_absolute()
        assert Path(engine.output_dir).is_absolute()
        assert "graded_videos" in str(engine.output_dir)

def test_apply_custom_lut_path_escaping(tmp_path, mock_ffmpeg):
    video = tmp_path / "input.mp4"
    video.write_text("dummy video", encoding="utf-8")
    
    lut_file_path = "C:\\dummy_dir\\preset.cube"
    
    with patch("shutil.which", return_value=mock_ffmpeg), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("color_grading.ProgressivePreview") as mock_preview_cls, \
         patch("color_grading.PreviewReportGenerator") as mock_gen_cls:
         
        mock_run.return_value = MagicMock(returncode=0)
        mock_preview = MagicMock()
        mock_preview.output_dir = tmp_path / "preview"
        mock_preview_cls.return_value = mock_preview
        
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen
        
        engine = ColorGrading()
        out_path = engine.apply_custom_lut(str(video), lut_file_path)
        
        assert out_path is not None
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        
        assert "-vf" in cmd
        vf_arg = cmd[cmd.index("-vf")+1]
        assert "lut3d=C\\:/dummy_dir/preset.cube" in vf_arg

def test_escape_filter_path_with_spaces():
    from color_grading import _escape_filter_path
    path_with_spaces = r"C:\My Folder\preset name.cube"
    escaped = _escape_filter_path(path_with_spaces)
    assert "C\\:/My Folder/preset name.cube" in escaped
