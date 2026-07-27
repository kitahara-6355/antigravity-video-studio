import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open
import PIL
from PIL import Image, ImageFont

# preview_report_generator 欠損対策のダミー登録
sys.modules["preview_report_generator"] = MagicMock()
sys.modules["preview_report_generator"].PreviewReportGenerator = MagicMock

# パス設定: backend の親(プロジェクトルート)と backend 自体を sys.path に追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.hybrid_pipeline import get_short_path, create_theme_telop, run_ffmpeg, hybrid_pipeline

# 1. get_short_path のテスト
def test_get_short_path_not_exists():
    with patch("backend.hybrid_pipeline.os.path.exists", return_value=False):
        expected = os.path.abspath("dummy_path")
        assert get_short_path("dummy_path") == expected

def test_get_short_path_success():
    with patch("backend.hybrid_pipeline.os.path.exists", return_value=True), \
         patch("backend.hybrid_pipeline._GetShortPathNameW", return_value=10) as mock_win_api, \
         patch("backend.hybrid_pipeline.ctypes.create_unicode_buffer") as mock_buf:
        mock_buf.return_value.value = "short_path"
        assert get_short_path("dummy_path") == "short_path"

def test_get_short_path_buffer_retry():
    with patch("backend.hybrid_pipeline.os.path.exists", return_value=True), \
         patch("backend.hybrid_pipeline._GetShortPathNameW", side_effect=[300, 10]) as mock_win_api, \
         patch("backend.hybrid_pipeline.ctypes.create_unicode_buffer") as mock_buf:
        buf_mock = MagicMock()
        buf_mock.value = "short_path_retry"
        mock_buf.return_value = buf_mock
        assert get_short_path("dummy_path") == "short_path_retry"

def test_get_short_path_error():
    with patch("backend.hybrid_pipeline.os.path.exists", return_value=True), \
         patch("backend.hybrid_pipeline._GetShortPathNameW", return_value=0):
        expected = os.path.abspath("dummy_path")
        assert get_short_path("dummy_path") == expected


# 2. create_theme_telop のテスト
def test_create_theme_telop_font_fallback():
    with patch("PIL.ImageFont.truetype", side_effect=[OSError("Font not found"), MagicMock()]), \
         patch("PIL.Image.new") as mock_new, \
         patch("PIL.Image.open") as mock_open_img:
        mock_img = MagicMock()
        mock_new.return_value = mock_img
       
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 30)
        with patch("PIL.ImageDraw.Draw", return_value=mock_draw):
            create_theme_telop("test", "output.png", include_logo=False)

def test_create_theme_telop_font_fail_all():
    with patch("PIL.ImageFont.truetype", side_effect=[OSError("Font not found"), OSError("Fallback failed")]):
        with pytest.raises(OSError):
            create_theme_telop("test", "output.png", include_logo=False)

def test_create_theme_telop_with_logo():
    with patch("PIL.ImageFont.truetype") as mock_font, \
         patch("PIL.Image.new") as mock_new, \
         patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw_class:
       
        mock_img = MagicMock()
        mock_new.return_value = mock_img
       
        mock_logo = MagicMock()
        mock_open_img.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo
        mock_logo.resize.return_value = mock_logo
       
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 30)
        mock_draw_class.return_value = mock_draw
       
        create_theme_telop("test", "output.png", include_logo=True)
       
        mock_open_img.assert_called()
        mock_logo.resize.assert_called()
        mock_img.paste.assert_called()
        mock_img.save.assert_called_with("output.png")


# 3. run_ffmpeg のテスト
def test_run_ffmpeg_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert run_ffmpeg(["ffmpeg", "cmd"], "desc") is True

def test_run_ffmpeg_failure_with_stderr():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error logs"
        assert run_ffmpeg(["ffmpeg", "cmd"], "desc") is False

def test_run_ffmpeg_failure_no_stderr():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = None
        assert run_ffmpeg(["ffmpeg", "cmd"], "desc") is False


# 4. hybrid_pipeline のテスト
def mock_subprocess_run(cmd, *args, **kwargs):
    res = MagicMock()
    res.returncode = 0
    if isinstance(cmd, list) and cmd[0] == "ffprobe":
        res.stdout = "100.0\n"
    else:
        res.stdout = ""
    res.stderr = ""
    return res

def test_hybrid_pipeline_success():
    with patch("backend.hybrid_pipeline.Path.mkdir"), \
         patch("backend.hybrid_pipeline.Path.exists", return_value=True), \
         patch("backend.hybrid_pipeline.Path.stat") as mock_stat, \
         patch("backend.hybrid_pipeline.create_theme_telop") as mock_telop, \
         patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x), \
         patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch("backend.hybrid_pipeline.ProgressivePreview") as mock_preview_cls, \
         patch("backend.hybrid_pipeline.PreviewReportGenerator") as mock_gen_cls:
       
        mock_stat.return_value.st_size = 1024 * 1024 * 50  # 50MB
       
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        mock_gen = MagicMock()
        mock_gen_cls.return_value = mock_gen
       
        res = hybrid_pipeline()
       
        assert res is not None
        assert "soul_narrative_master.mp4" in res["master"]
        assert "soul_narrative_FINAL.mp4" in res["final"]

def test_hybrid_pipeline_preview_exception():
    with patch("backend.hybrid_pipeline.Path.mkdir"), \
         patch("backend.hybrid_pipeline.Path.exists", return_value=True), \
         patch("backend.hybrid_pipeline.Path.stat") as mock_stat, \
         patch("backend.hybrid_pipeline.create_theme_telop"), \
         patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x), \
         patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch("backend.hybrid_pipeline.ProgressivePreview") as mock_preview_cls:
       
        mock_stat.return_value.st_size = 1024 * 1024 * 50
       
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = RuntimeError("Preview Error")
        mock_preview_cls.return_value = mock_preview
       
        res = hybrid_pipeline()
        assert res is not None

def test_hybrid_pipeline_no_final_output():
    def exists_side_effect(self_obj):
        if "soul_narrative_FINAL.mp4" in str(self_obj):
            return False
        return True
       
    with patch("backend.hybrid_pipeline.Path.mkdir"), \
         patch("backend.hybrid_pipeline.Path.exists", exists_side_effect), \
         patch("backend.hybrid_pipeline.create_theme_telop"), \
         patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x), \
         patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch("backend.hybrid_pipeline.ProgressivePreview"):
       
        res = hybrid_pipeline()
        assert res is None

def test_script_execution_via_runpy():
    import runpy
    mock_pp = MagicMock()
    mock_prg = MagicMock()
    with patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run), \
         patch("backend.hybrid_pipeline.Path.mkdir"), \
         patch("backend.hybrid_pipeline.Path.exists", return_value=True), \
         patch("backend.hybrid_pipeline.Path.stat") as mock_stat, \
         patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch.dict("sys.modules", {"progressive_preview": mock_pp, "preview_report_generator": mock_prg}), \
         patch("PIL.Image.open"), \
         patch("PIL.Image.new"), \
         patch("PIL.ImageFont.truetype"), \
         patch("time.time", return_value=1.0):
        
        mock_stat.return_value.st_size = 1024 * 1024 * 50
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path("backend/hybrid_pipeline.py", run_name="__main__")
        assert excinfo.value.code == 0

def test_script_execution_via_runpy_failed():
    import runpy
    mock_pp = MagicMock()
    mock_prg = MagicMock()
    def exists_side_effect(self_obj):
        if "soul_narrative_FINAL.mp4" in str(self_obj):
            return False
        return True

    with patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run), \
         patch("backend.hybrid_pipeline.Path.mkdir"), \
         patch("backend.hybrid_pipeline.Path.exists", exists_side_effect), \
         patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch.dict("sys.modules", {"progressive_preview": mock_pp, "preview_report_generator": mock_prg}), \
         patch("PIL.Image.open"), \
         patch("PIL.Image.new"), \
         patch("PIL.ImageFont.truetype"), \
         patch("time.time", return_value=1.0):
        
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path("backend/hybrid_pipeline.py", run_name="__main__")
        assert excinfo.value.code == 1


# 5. main関数のテストおよび例外キャッチのテスト
def test_main_success():
    from backend.hybrid_pipeline import main
    with patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run),          patch("backend.hybrid_pipeline.Path.mkdir"),          patch("backend.hybrid_pipeline.Path.exists", return_value=True),          patch("backend.hybrid_pipeline.Path.stat") as mock_stat,          patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x),          patch("builtins.open", mock_open()) as mock_file,          patch("backend.hybrid_pipeline.ProgressivePreview"),          patch("backend.hybrid_pipeline.PreviewReportGenerator"),          patch("PIL.Image.open"),          patch("PIL.Image.new"),          patch("PIL.ImageFont.truetype"),          patch("time.time", return_value=1.0):
       
        mock_stat.return_value.st_size = 1024 * 1024 * 50
        assert main() == 0

def test_main_failed():
    from backend.hybrid_pipeline import main
    def exists_side_effect(self_obj):
        if "soul_narrative_FINAL.mp4" in str(self_obj):
            return False
        return True
       
    with patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run),          patch("backend.hybrid_pipeline.Path.mkdir"),          patch("backend.hybrid_pipeline.Path.exists", exists_side_effect),          patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x),          patch("builtins.open", mock_open()) as mock_file,          patch("backend.hybrid_pipeline.ProgressivePreview"),          patch("PIL.Image.open"),          patch("PIL.Image.new"),          patch("PIL.ImageFont.truetype"),          patch("time.time", return_value=1.0):
       
        assert main() == 1

def test_hybrid_pipeline_snapshot_exception_handled():
    with patch("backend.hybrid_pipeline.Path.mkdir"),          patch("backend.hybrid_pipeline.Path.exists", return_value=True),          patch("backend.hybrid_pipeline.Path.stat") as mock_stat,          patch("backend.hybrid_pipeline.create_theme_telop") as mock_telop,          patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x),          patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run),          patch("builtins.open", mock_open()) as mock_file,          patch("backend.hybrid_pipeline.ProgressivePreview") as mock_preview_cls,          patch("backend.hybrid_pipeline.PreviewReportGenerator") as mock_gen_cls:
       
        mock_stat.return_value.st_size = 1024 * 1024 * 50
       
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = OSError("Mocked disk error")
        mock_preview_cls.return_value = mock_preview
       
        res = hybrid_pipeline()
        assert res is not None
        assert "soul_narrative_master.mp4" in res["master"]

def test_hybrid_pipeline_report_exception_handled():
    with patch("backend.hybrid_pipeline.Path.mkdir"),          patch("backend.hybrid_pipeline.Path.exists", return_value=True),          patch("backend.hybrid_pipeline.Path.stat") as mock_stat,          patch("backend.hybrid_pipeline.create_theme_telop") as mock_telop,          patch("backend.hybrid_pipeline.get_short_path", side_effect=lambda x: x),          patch("backend.hybrid_pipeline.subprocess.run", side_effect=mock_subprocess_run),          patch("builtins.open", mock_open()) as mock_file,          patch("backend.hybrid_pipeline.ProgressivePreview") as mock_preview_cls,          patch("backend.hybrid_pipeline.PreviewReportGenerator") as mock_gen_cls:
       
        mock_stat.return_value.st_size = 1024 * 1024 * 50
       
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
       
        mock_gen = MagicMock()
        mock_gen.generate_from_session_dir.side_effect = RuntimeError("Report error")
        mock_gen_cls.return_value = mock_gen
       
        res = hybrid_pipeline()
        assert res is not None
        assert "soul_narrative_master.mp4" in res["master"]

def test_if_name_main_execution():
    from importlib.machinery import SourceFileLoader
    import sys
    mock_pp = MagicMock()
    mock_prg = MagicMock()
    with patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("pathlib.Path.mkdir"), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat, \
         patch("builtins.open", mock_open()) as mock_file, \
         patch("PIL.Image.open"), \
         patch("PIL.Image.new"), \
         patch("PIL.ImageFont.truetype"), \
         patch("sys.exit") as mock_exit, \
         patch.dict("sys.modules", {"progressive_preview": mock_pp, "preview_report_generator": mock_prg}):
        
        mock_stat.return_value.st_size = 1024 * 1024 * 50
        loader = SourceFileLoader('__main__', 'backend/hybrid_pipeline.py')
        try:
            loader.load_module()
        except SystemExit:
            pass
        mock_exit.assert_called_once_with(0)

# 新規追加されたテストケース
def test_run_ffmpeg_timeout():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=600)):
        assert run_ffmpeg(["ffmpeg", "cmd"], "desc", timeout=600) is False

def test_create_theme_telop_logo_open_error():
    with patch("PIL.ImageFont.truetype") as mock_font, \
         patch("PIL.Image.new") as mock_new, \
         patch("PIL.Image.open", side_effect=FileNotFoundError("Logo not found")), \
         patch("PIL.ImageDraw.Draw") as mock_draw_class:
        
        mock_img = MagicMock()
        mock_new.return_value = mock_img
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = (0, 0, 100, 30)
        mock_draw_class.return_value = mock_draw
        
        with pytest.raises(FileNotFoundError):
            create_theme_telop("test", "output.png", include_logo=True)
