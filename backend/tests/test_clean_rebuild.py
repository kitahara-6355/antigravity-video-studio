import sys
import os
import pytest
import stat
import runpy
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

# backend ディレクトリを sys.path に追加してインポート可能にする
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import clean_rebuild
import importlib

@pytest.fixture(autouse=True)
def reload_clean_rebuild():
    import sys
    if "clean_rebuild" in sys.modules:
        del sys.modules["clean_rebuild"]
    import clean_rebuild
    globals()["clean_rebuild"] = clean_rebuild

def test_get_short_path_exists_and_success():
    with patch("os.path.abspath", return_value="C:\\test\\longpath"), \
         patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", return_value=10) as mock_win_api, \
         patch("ctypes.create_unicode_buffer") as mock_buf:
        
        mock_buf_instance = MagicMock()
        mock_buf_instance.value = "C:\\test\\short"
        mock_buf.return_value = mock_buf_instance
        
        res = clean_rebuild.get_short_path("C:\\test\\longpath")
        assert res == "C:\\test\\short"
        mock_win_api.assert_called_once()

def test_get_short_path_not_exists():
    with patch("os.path.abspath", return_value="C:\\test\\nonexistent"), \
         patch("os.path.exists", return_value=False):
        res = clean_rebuild.get_short_path("C:\\test\\nonexistent")
        assert res == "C:\\test\\nonexistent"

def test_get_short_path_buffer_resize():
    side_effects = [512, 10]
    with patch("os.path.abspath", return_value="C:\\test\\longpath"), \
         patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", side_effect=side_effects) as mock_win_api, \
         patch("ctypes.create_unicode_buffer") as mock_buf:
        
        mock_buf_instance = MagicMock()
        mock_buf_instance.value = "C:\\test\\short"
        mock_buf.return_value = mock_buf_instance
        
        res = clean_rebuild.get_short_path("C:\\test\\longpath")
        assert res == "C:\\test\\short"
        assert mock_win_api.call_count == 2

def test_get_short_path_error():
    with patch("os.path.abspath", return_value="C:\\test\\longpath"), \
         patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", return_value=0) as mock_win_api, \
         patch("ctypes.create_unicode_buffer") as mock_buf:
        
        res = clean_rebuild.get_short_path("C:\\test\\longpath")
        assert res == "C:\\test\\longpath"

def test_create_premium_branding_success():
    with patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.Image.new") as mock_new_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw, \
         patch("PIL.ImageFont.truetype") as mock_font:
        
        mock_logo = MagicMock()
        mock_open_img.return_value.convert.return_value = mock_logo
        
        mock_telop = MagicMock()
        mock_new_img.side_effect = [mock_telop, MagicMock()]
        
        mock_draw_instance = MagicMock()
        mock_draw_instance.textbbox.return_value = (0, 0, 100, 20)
        mock_draw.return_value = mock_draw_instance
        
        res = clean_rebuild.create_premium_branding()
        assert "premium_branding.png" in str(res)
        mock_font.assert_any_call(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        mock_logo.thumbnail.assert_called_once()
        assert mock_logo.thumbnail.call_args[0][0] == (28, 45)

def test_create_premium_branding_font_fallback():
    def font_side_effect(*args, **kwargs):
        if "YuGothB.ttc" in args[0]:
            raise OSError("Font load error")
        return MagicMock()
        
    with patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.Image.new") as mock_new_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw, \
         patch("PIL.ImageFont.truetype", side_effect=font_side_effect) as mock_font:
        
        mock_logo = MagicMock()
        mock_open_img.return_value.convert.return_value = mock_logo
        mock_new_img.side_effect = [MagicMock(), MagicMock()]
        
        mock_draw_instance = MagicMock()
        mock_draw_instance.textbbox.return_value = (0, 0, 100, 20)
        mock_draw.return_value = mock_draw_instance
        
        res = clean_rebuild.create_premium_branding()
        assert "premium_branding.png" in str(res)
        mock_font.assert_any_call(r"C:\Windows\Fonts\msgothic.ttc", 20)

def test_create_premium_branding_all_fonts_failed():
    def font_side_effect(*args, **kwargs):
        raise OSError("Font load error")
        
    with patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.Image.new") as mock_new_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw, \
         patch("PIL.ImageFont.truetype", side_effect=font_side_effect) as mock_font:
        
        mock_logo = MagicMock()
        mock_open_img.return_value.convert.return_value = mock_logo
        mock_new_img.side_effect = [MagicMock(), MagicMock()]
        
        mock_draw_instance = MagicMock()
        mock_draw_instance.textbbox.return_value = (0, 0, 100, 20)
        mock_draw.return_value = mock_draw_instance
        
        with pytest.raises(OSError):
            clean_rebuild.create_premium_branding()

def test_run_ffmpeg_success():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        res = clean_rebuild.run_ffmpeg(["ffmpeg"], "test command")
        assert res is True
        mock_run.assert_called_once()

def test_run_ffmpeg_failed():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "some error description"
    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        res = clean_rebuild.run_ffmpeg(["ffmpeg"], "test command")
        assert res is False
        mock_run.assert_called_once()

def path_stat_side_effect(self, *args, **kwargs):
    mock_res = MagicMock()
    path_str = str(self).replace("\\", "/")
    if "clean_rebuild" in path_str and not path_str.endswith(".mp4") and not path_str.endswith(".txt"):
        mock_res.st_mode = stat.S_IFDIR | 0o755
        mock_res.st_size = 4096
    else:
        mock_res.st_mode = stat.S_IFREG | 0o644
        mock_res.st_size = 100 * 1024 * 1024
    return mock_res

def test_clean_rebuild_success():
    def subprocess_run_side_effect(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "ffprobe" in cmd:
            mock_proc.stdout = "2400.0\n"
        else:
            mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    def path_exists_side_effect(*args, **kwargs):
        return True

    with patch("subprocess.run", side_effect=subprocess_run_side_effect), \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", side_effect=path_exists_side_effect), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("clean_rebuild.PreviewReportGenerator") as mock_generator_cls, \
         patch("builtins.open", mock_open()):
        
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        mock_preview.output_dir = "/path/to/output"
        
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res

def test_clean_rebuild_no_final_output():
    def subprocess_run_side_effect(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    def path_exists_side_effect(self, *args, **kwargs):
        if "soul_narrative_CLEAN_FINAL.mp4" in str(self):
            return False
        return True

    with patch("subprocess.run", side_effect=subprocess_run_side_effect), \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", path_exists_side_effect), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("builtins.open", mock_open()):
        
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        
        res = clean_rebuild.clean_rebuild()
        assert res is None

def test_clean_rebuild_exceptions_handled():
    def subprocess_run_side_effect(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "ffprobe" in cmd:
            mock_proc.stdout = "2400.0\n"
        else:
            mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    def path_exists_side_effect(*args, **kwargs):
        return True

    with patch("subprocess.run", side_effect=subprocess_run_side_effect), \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", side_effect=path_exists_side_effect), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("clean_rebuild.PreviewReportGenerator") as mock_generator_cls, \
         patch("builtins.open", mock_open()):
        
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = Exception("Snapshot failed")
        mock_preview_cls.return_value = mock_preview
        mock_preview.output_dir = "/path/to/output"
        
        mock_generator = MagicMock()
        mock_generator.generate_from_session_dir.side_effect = Exception("Report gen failed")
        mock_generator_cls.return_value = mock_generator
        
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res

def test_main_block_success():
    orig_modules = sys.modules.copy()
    try:
        mock_subprocess = MagicMock()
        def sub_run(cmd, *args, **kwargs):
            p = MagicMock()
            p.returncode = 0
            if any("ffprobe" in str(c) for c in cmd):
                p.stdout = "2400.0\n"
            else:
                p.stdout = ""
            p.stderr = ""
            return p
        mock_subprocess.run.side_effect = sub_run
        sys.modules["subprocess"] = mock_subprocess

        mock_pil = MagicMock()
        mock_image = MagicMock()
        mock_image.new.return_value = MagicMock()
        mock_image.open.return_value.convert.return_value = MagicMock()
        mock_draw = MagicMock()
        mock_draw.Draw.return_value.textbbox.return_value = (0, 0, 100, 20)
        sys.modules["PIL"] = mock_pil
        sys.modules["PIL.Image"] = mock_image
        sys.modules["PIL.ImageDraw"] = mock_draw
        sys.modules["PIL.ImageFont"] = MagicMock()

        mock_pp = MagicMock()
        mock_pp_cls = MagicMock(return_value=mock_pp)
        mock_pp.output_dir = "/path/to/output"
        mock_prg = MagicMock()
        mock_prg_cls = MagicMock(return_value=mock_prg)
        
        sys.modules["progressive_preview"] = MagicMock(ProgressivePreview=mock_pp_cls)
        sys.modules["services.preview_report_generator"] = MagicMock(PreviewReportGenerator=mock_prg_cls)

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.GetShortPathNameW = MagicMock(return_value=10)
        sys.modules["ctypes"] = mock_ctypes

        def path_exists_side_effect(*args, **kwargs):
            return True

        with patch("pathlib.Path.exists", path_exists_side_effect), \
             patch("pathlib.Path.stat", path_stat_side_effect), \
             patch("builtins.open", mock_open()):
             
            if "clean_rebuild" in sys.modules:
                del sys.modules["clean_rebuild"]
            runpy.run_module("clean_rebuild", run_name="__main__")
            
    finally:
        for k in list(sys.modules.keys()):
            if k not in orig_modules:
                del sys.modules[k]
            else:
                sys.modules[k] = orig_modules[k]

def test_clean_rebuild_missing_scene_and_segment():
    def subprocess_run_side_effect(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "ffprobe" in cmd:
            mock_proc.stdout = "2400.0\n"
        else:
            mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    def path_exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "s02_clean.mp4" in path_str or "cut_seg3.mp4" in path_str:
            return False
        return True

    m_open = mock_open()
    with patch("subprocess.run", side_effect=subprocess_run_side_effect), \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", path_exists_side_effect), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("clean_rebuild.PreviewReportGenerator") as mock_generator_cls, \
         patch("builtins.open", m_open):
        
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        mock_preview.output_dir = "/path/to/output"
        
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res
        
        written_data = []
        for call in m_open.return_value.write.call_args_list:
            written_data.append(call[0][0])
            
        full_write_content = "".join(written_data)
        assert "s01_clean.mp4" in full_write_content
        assert "s02_clean.mp4" not in full_write_content
        assert "s03_clean.mp4" in full_write_content
        assert "s04_clean.mp4" in full_write_content
        
        assert "cut_seg1.mp4" in full_write_content
        assert "cut_seg2.mp4" in full_write_content
        assert "cut_seg3.mp4" not in full_write_content
        assert "cut_seg4.mp4" in full_write_content


def test_main_block_failed():
    orig_modules = sys.modules.copy()
    try:
        mock_subprocess = MagicMock()
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        sys.modules["subprocess"] = mock_subprocess

        mock_pil = MagicMock()
        mock_image = MagicMock()
        mock_image.new.return_value = MagicMock()
        mock_image.open.return_value.convert.return_value = MagicMock()
        mock_draw = MagicMock()
        mock_draw.Draw.return_value.textbbox.return_value = (0, 0, 100, 20)
        sys.modules["PIL"] = mock_pil
        sys.modules["PIL.Image"] = mock_image
        sys.modules["PIL.ImageDraw"] = mock_draw
        sys.modules["PIL.ImageFont"] = MagicMock()

        mock_pp = MagicMock()
        mock_pp_cls = MagicMock(return_value=mock_pp)
        sys.modules["progressive_preview"] = MagicMock(ProgressivePreview=mock_pp_cls)
        sys.modules["services.preview_report_generator"] = MagicMock(PreviewReportGenerator=MagicMock())

        mock_ctypes = MagicMock()
        mock_ctypes.windll.kernel32.GetShortPathNameW = MagicMock(return_value=10)
        sys.modules["ctypes"] = mock_ctypes

        def path_exists_side_effect(self, *args, **kwargs):
            if "soul_narrative_CLEAN_FINAL.mp4" in str(self):
                return False
            return True

        with patch("pathlib.Path.exists", path_exists_side_effect), \
             patch("pathlib.Path.stat", path_stat_side_effect), \
             patch("builtins.open", mock_open()):
             
            if "clean_rebuild" in sys.modules:
                del sys.modules["clean_rebuild"]
            runpy.run_module("clean_rebuild", run_name="__main__")
            
    finally:
        for k in list(sys.modules.keys()):
            if k not in orig_modules:
                del sys.modules[k]
            else:
                sys.modules[k] = orig_modules[k]


def test_run_ffmpeg_timeout_exception():
    """run_ffmpeg がタイムアウト例外を投げた場合の挙動をテスト"""
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=60)) as mock_run:
        res = clean_rebuild.run_ffmpeg(["ffmpeg"], "timeout command")
        assert res is False
        mock_run.assert_called_once()


def test_clean_rebuild_preview_logger_exception():
    """clean_rebuild で ProgressivePreview が失敗した際の logger.exception をテスト"""
    import subprocess
    with patch("clean_rebuild.logger") as mock_logger, \
         patch("subprocess.run") as mock_run, \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("builtins.open", mock_open()):
        
        mock_preview = MagicMock()
        mock_preview.snapshot_step.side_effect = Exception("Snapshot error")
        mock_preview_cls.return_value = mock_preview
        
        mock_run.return_value = MagicMock(returncode=0, stdout="2400.0\n")
        
        clean_rebuild.clean_rebuild()
        mock_logger.exception.assert_any_call("Progressive preview snapshot failed for concatenation")


def test_clean_rebuild_ffprobe_invalid_output():
    """ffprobe が非数値を出力した場合に例外を投げず、正常に完了することをテスト"""
    import subprocess
    def subprocess_run_side_effect(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "ffprobe" in cmd:
            mock_proc.stdout = "not_a_float\n"
        else:
            mock_proc.stdout = ""
        return mock_proc

    with patch("subprocess.run", side_effect=subprocess_run_side_effect), \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("clean_rebuild.PreviewReportGenerator") as mock_generator_cls, \
         patch("builtins.open", mock_open()):
         
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        mock_preview.output_dir = "/path/to/output"
        
        mock_generator = MagicMock()
        mock_generator_cls.return_value = mock_generator
        
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res


def test_create_premium_branding_integration_resizing(tmp_path):
    """実際の画像ライブラリを使用してロゴのリサイズと貼り付けが行われることを検証"""
    from PIL import Image, ImageFont
    import clean_rebuild
    
    # logos ディレクトリの準備
    logos_dir = tmp_path / "backend" / "branding" / "logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    
    # 巨大なダミーのロゴ画像 (900x1800) を作成して保存
    dummy_logo = Image.new('RGBA', (900, 1800), (255, 0, 0, 255))
    dummy_logo.save(logos_dir / "brand_logo.png")
    
    # フォントはデフォルトフォントを返すように mock してエラーを防止
    default_font = ImageFont.load_default()
    
    with patch("pathlib.Path.resolve") as mock_resolve, \
         patch("PIL.ImageFont.truetype", return_value=default_font):
        
        # mock_resolve.return_value の parent.parent が tmp_path になるように設定
        mock_resolve.return_value = Path(tmp_path) / "backend" / "clean_rebuild.py"
        
        # 実行
        out_path = clean_rebuild.create_premium_branding()
        
        # 結果の検証
        assert Path(out_path).exists()
        img = Image.open(out_path)
        assert img.size == (358, 45)
        # 生成された画像を開いて、ロゴ部分（左側28x45）に赤色（255, 0, 0）が正しくリサイズされて含まれているか確認
        r, g, b, a = img.getpixel((0, 0))
        assert r == 255
        assert g == 0
        assert b == 0


def test_get_short_path_no_windows_api():
    """_GetShortPathNameW が None の場合に get_short_path が元のパスを正常に返すことをテスト"""
    with patch("clean_rebuild._GetShortPathNameW", None), \
         patch("os.path.abspath", return_value="C:\\test\\path"), \
         patch("os.path.exists", return_value=True):
        res = clean_rebuild.get_short_path("C:\\test\\path")
        assert res == "C:\\test\\path"


def test_run_ffmpeg_filenotfound_exception():
    """run_ffmpeg が FileNotFoundError を投げた場合の挙動をテスト"""
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")) as mock_run:
        res = clean_rebuild.run_ffmpeg(["ffmpeg"], "missing command")
        assert res is False
        mock_run.assert_called_once()


def test_run_ffmpeg_subprocess_error():
    """run_ffmpeg が SubprocessError を投げた場合の挙動をテスト"""
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("subprocess error")) as mock_run:
        res = clean_rebuild.run_ffmpeg(["ffmpeg"], "error command")
        assert res is False
        mock_run.assert_called_once()


def test_initialize_short_path_api_attribute_error():
    """ctypes.windll から kernel32 をロードする際に AttributeError が発生した場合をテスト"""
    import importlib
    import ctypes
    from unittest.mock import patch
    
    class MockWindll:
        @property
        def kernel32(self):
            raise AttributeError("Mock kernel32 not found")
            
    mock_windll = MockWindll()
    
    with patch("ctypes.windll", mock_windll, create=True):
        import clean_rebuild
        importlib.reload(clean_rebuild)
        assert clean_rebuild._GetShortPathNameW is None


def test_get_short_path_type_error():
    """get_short_path 内で TypeError などの例外が発生した場合のハンドリングをテスト"""
    with patch("os.path.abspath", return_value="C:\\test\\longpath"), \
         patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", side_effect=TypeError("Mocked type error")) as mock_win_api:
        
        res = clean_rebuild.get_short_path("C:\\test\\longpath")
        assert res == "C:\\test\\longpath"


def test_create_premium_branding_logo_missing():
    """ロゴ画像が存在しない場合でも、クラッシュせずにブランディング画像が生成されることを検証"""
    with patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.Image.new") as mock_new_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw, \
         patch("PIL.ImageFont.truetype") as mock_font, \
         patch("pathlib.Path.exists", return_value=False):
        
        mock_telop = MagicMock()
        mock_new_img.side_effect = [mock_telop, MagicMock()]
        
        mock_draw_instance = MagicMock()
        mock_draw_instance.textbbox.return_value = (0, 0, 100, 20)
        mock_draw.return_value = mock_draw_instance
        
        res = clean_rebuild.create_premium_branding()
        assert "premium_branding.png" in str(res)
        mock_open_img.assert_not_called()


def test_create_premium_branding_default_font_fallback():
    """すべてのシステムフォントの読み込みに失敗した場合に、ImageFont.load_default() が呼ばれることを検証"""
    def font_side_effect(*args, **kwargs):
        raise OSError("Font load error")
        
    with patch("PIL.Image.open") as mock_open_img, \
         patch("PIL.Image.new") as mock_new_img, \
         patch("PIL.ImageDraw.Draw") as mock_draw, \
         patch("PIL.ImageFont.truetype", side_effect=font_side_effect) as mock_font, \
         patch("PIL.ImageFont.load_default") as mock_default_font:
        
        mock_logo = MagicMock()
        mock_open_img.return_value.convert.return_value = mock_logo
        mock_new_img.side_effect = [MagicMock(), MagicMock()]
        
        mock_draw_instance = MagicMock()
        mock_draw_instance.textbbox.return_value = (0, 0, 100, 20)
        mock_draw.return_value = mock_draw_instance
        
        mock_default_font.return_value = MagicMock()
        
        res = clean_rebuild.create_premium_branding()
        assert "premium_branding.png" in str(res)
        mock_default_font.assert_called_once()


def test_clean_rebuild_ffmpeg_failure_aborts():
    """中間の run_ffmpeg が失敗した場合に clean_rebuild が None を返すことを検証"""
    with patch("clean_rebuild.run_ffmpeg", return_value=False) as mock_run, \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls:
        
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        
        res = clean_rebuild.clean_rebuild()
        assert res is None
        mock_run.assert_called_once()


def test_clean_rebuild_concat_empty_aborts():
    """結合対象のシーンファイルが1つも存在しない場合、ffmpegを呼び出さずに None を返すことを検証"""
    def path_exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "s01_clean.mp4" in path_str or "s02_clean.mp4" in path_str or "s03_clean.mp4" in path_str or "s04_clean.mp4" in path_str:
            return False
        return True

    with patch("clean_rebuild.run_ffmpeg", return_value=True) as mock_run, \
         patch("clean_rebuild.create_premium_branding", return_value="/path/to/branding.png"), \
         patch("clean_rebuild.get_short_path", side_effect=lambda x: x), \
         patch("pathlib.Path.exists", path_exists_side_effect), \
         patch("pathlib.Path.stat", path_stat_side_effect), \
         patch("clean_rebuild.ProgressivePreview") as mock_preview_cls, \
         patch("builtins.open", mock_open()):
        
        mock_preview = MagicMock()
        mock_preview_cls.return_value = mock_preview
        
        res = clean_rebuild.clean_rebuild()
        assert res is None
        assert mock_run.call_count == 4

