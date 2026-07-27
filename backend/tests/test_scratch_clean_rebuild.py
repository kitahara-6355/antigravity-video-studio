import sys
import os
from pathlib import Path as RealPath
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

# backend を PYTHONPATH に追加
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# 依存モジュールのインポートエラーを防ぐため、sys.modules にダミーを登録
mock_progressive_preview = MagicMock()
mock_preview_report_generator = MagicMock()

sys.modules["progressive_preview"] = mock_progressive_preview
sys.modules["services.preview_report_generator"] = mock_preview_report_generator

# 先にモジュールをインポート
import clean_rebuild
import importlib

@pytest.fixture(autouse=True)
def reload_clean_rebuild():
    import sys
    if "clean_rebuild" in sys.modules:
        del sys.modules["clean_rebuild"]
    import clean_rebuild
    globals()["clean_rebuild"] = clean_rebuild

def get_path_patch(tmp_path):
    root_dir = os.path.dirname(backend_dir)
    def mock_path(*args, **kwargs):
        if args and isinstance(args[0], str):
            arg_str = args[0]
            if "video-automation" in arg_str:
                arg_str = arg_str.replace(r"C:\Users\PC_User\Desktop\script\video-automation", str(tmp_path))
            if root_dir in arg_str:
                arg_str = arg_str.replace(root_dir, str(tmp_path))
            norm_arg = os.path.normpath(arg_str)
            norm_root = os.path.normpath(root_dir)
            if norm_root in norm_arg:
                arg_str = norm_arg.replace(norm_root, str(tmp_path))
            return RealPath(arg_str, *args[1:], **kwargs)
        return RealPath(*args, **kwargs)
    return mock_path

def create_dummy_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new('RGBA', (1, 1), color=(0, 0, 0, 0))
    img.save(path)

# test_get_short_path のテスト
def test_get_short_path_not_exists():
    with patch("os.path.exists", return_value=False):
        res = clean_rebuild.get_short_path("dummy_path")
        assert res == os.path.abspath("dummy_path")

def test_get_short_path_exists_and_success():
    mock_get_short = MagicMock(return_value=10) # needed = 10 (<= 256)
    with patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", mock_get_short), \
         patch("ctypes.create_unicode_buffer") as mock_buf:
        mock_buf.return_value.value = "short_path_val"
        res = clean_rebuild.get_short_path("dummy_path")
        assert res == "short_path_val"

def test_get_short_path_exists_loop():
    mock_get_short = MagicMock(side_effect=[300, 10])
    with patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", mock_get_short), \
         patch("ctypes.create_unicode_buffer") as mock_buf:
        mock_buf.return_value.value = "looped_short_path"
        res = clean_rebuild.get_short_path("dummy_path")
        assert res == "looped_short_path"
        assert mock_get_short.call_count == 2

def test_get_short_path_error():
    mock_get_short = MagicMock(return_value=0)
    with patch("os.path.exists", return_value=True), \
         patch("clean_rebuild._GetShortPathNameW", mock_get_short):
        res = clean_rebuild.get_short_path("dummy_path")
        assert res == os.path.abspath("dummy_path")

# test_create_premium_branding のテスト
def test_create_premium_branding_success_first_font():
    mock_logo = MagicMock()
    mock_logo.convert.return_value = mock_logo
    mock_telop = MagicMock()
    mock_draw = MagicMock()
    mock_draw.textbbox.return_value = (0, 0, 100, 20)
    mock_font = MagicMock()
    
    with patch("PIL.Image.open", return_value=mock_logo), \
         patch("PIL.Image.new") as mock_image_new, \
         patch("PIL.ImageDraw.Draw", return_value=mock_draw), \
         patch("PIL.ImageFont.truetype", return_value=mock_font) as mock_truetype:
        mock_image_new.side_effect = [mock_telop, MagicMock()]
        res = clean_rebuild.create_premium_branding()
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        assert "premium_branding.png" in str(res)

def test_create_premium_branding_fallback_font():
    mock_logo = MagicMock()
    mock_logo.convert.return_value = mock_logo
    mock_telop = MagicMock()
    mock_draw = MagicMock()
    mock_draw.textbbox.return_value = (0, 0, 100, 20)
    mock_font = MagicMock()
    
    def truetype_side_effect(font_path, size):
        if "YuGothB" in font_path:
            raise OSError("Font not found")
        return mock_font
        
    with patch("PIL.Image.open", return_value=mock_logo), \
         patch("PIL.Image.new") as mock_image_new, \
         patch("PIL.ImageDraw.Draw", return_value=mock_draw), \
         patch("PIL.ImageFont.truetype", side_effect=truetype_side_effect) as mock_truetype:
        mock_image_new.side_effect = [mock_telop, MagicMock()]
        res = clean_rebuild.create_premium_branding()
        assert mock_truetype.call_count == 2
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\msgothic.ttc", 20)

# test_run_ffmpeg のテスト
def test_run_ffmpeg_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        res = clean_rebuild.run_ffmpeg(["ffmpeg", "args"], "test_desc")
        assert res is True

def test_run_ffmpeg_failed_with_stderr():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "some error log"
    with patch("subprocess.run", return_value=mock_result):
        res = clean_rebuild.run_ffmpeg(["ffmpeg", "args"], "test_desc")
        assert res is False

def test_run_ffmpeg_failed_no_stderr():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = None
    with patch("subprocess.run", return_value=mock_result):
        res = clean_rebuild.run_ffmpeg(["ffmpeg", "args"], "test_desc")
        assert res is False

# clean_rebuild 全体および Progressive Preview のテスト
def test_clean_rebuild_success(tmp_path):
    mock_path_fn = get_path_patch(tmp_path)
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "シーン01_前編.mp4").touch()
    (raw_dir / "シーン02_ゲスト書道.mp4").touch()
    (raw_dir / "シーン03_後編01.mp4").touch()
    (raw_dir / "シーン04_後編02.mp4").touch()
    
    logo_path = tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    create_dummy_png(logo_path)
    
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "ffprobe" in cmd[0]:
            mock_res.stdout = "1800.0"
        elif "ffmpeg" in cmd[0]:
            out_file = cmd[-1]
            out_path = RealPath(out_file)
            if not out_path.is_absolute():
                out_path = tmp_path / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.touch()
        return mock_res
        
    mock_preview = MagicMock()
    mock_generator = MagicMock()
    mock_generator.return_value.generate_from_session_dir.return_value = "report_path"
    
    with patch("clean_rebuild.Path", mock_path_fn), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("clean_rebuild.ProgressivePreview", return_value=mock_preview), \
         patch("clean_rebuild.PreviewReportGenerator", mock_generator):
         
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res

def test_clean_rebuild_preview_exception(tmp_path):
    mock_path_fn = get_path_patch(tmp_path)
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "シーン01_前編.mp4").touch()
    (raw_dir / "シーン02_ゲスト書道.mp4").touch()
    (raw_dir / "シーン03_後編01.mp4").touch()
    (raw_dir / "シーン04_後編02.mp4").touch()
    
    logo_path = tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    create_dummy_png(logo_path)
    
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "ffprobe" in cmd[0]:
            mock_res.stdout = "1800.0"
        elif "ffmpeg" in cmd[0]:
            out_file = cmd[-1]
            out_path = RealPath(out_file)
            if not out_path.is_absolute():
                out_path = tmp_path / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.touch()
        return mock_res
        
    mock_preview = MagicMock()
    mock_preview.snapshot_step.side_effect = Exception("Preview Error")
    
    mock_generator = MagicMock()
    mock_generator.return_value.generate_from_session_dir.side_effect = Exception("Report Error")
    
    with patch("clean_rebuild.Path", mock_path_fn), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("clean_rebuild.ProgressivePreview", return_value=mock_preview), \
         patch("clean_rebuild.PreviewReportGenerator", mock_generator):
         
        res = clean_rebuild.clean_rebuild()
        assert res is not None
        assert "soul_narrative_CLEAN_FINAL.mp4" in res

def test_clean_rebuild_final_output_not_created(tmp_path):
    mock_path_fn = get_path_patch(tmp_path)
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "シーン01_前編.mp4").touch()
    (raw_dir / "シーン02_ゲスト書道.mp4").touch()
    (raw_dir / "シーン03_後編01.mp4").touch()
    (raw_dir / "シーン04_後編02.mp4").touch()
    
    logo_path = tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    create_dummy_png(logo_path)
    
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "ffprobe" in cmd[0]:
            mock_res.stdout = "1800.0"
        elif "ffmpeg" in cmd[0]:
            out_file = cmd[-1]
            if "soul_narrative_CLEAN_FINAL.mp4" not in out_file:
                out_path = RealPath(out_file)
                if not out_path.is_absolute():
                    out_path = tmp_path / out_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.touch()
        return mock_res
        
    with patch("clean_rebuild.Path", mock_path_fn), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("clean_rebuild.ProgressivePreview"), \
         patch("clean_rebuild.PreviewReportGenerator"):
         
        res = clean_rebuild.clean_rebuild()
        assert res is None

# __main__ ブロックの実行テスト (成功パターン)
def test_main_execution_success(tmp_path):
    mock_path_fn = get_path_patch(tmp_path)
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "シーン01_前編.mp4").touch()
    (raw_dir / "シーン02_ゲスト書道.mp4").touch()
    (raw_dir / "シーン03_後編01.mp4").touch()
    (raw_dir / "シーン04_後編02.mp4").touch()
    
    logo_path = tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    create_dummy_png(logo_path)
    
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "ffprobe" in cmd[0]:
            mock_res.stdout = "1800.0"
        elif "ffmpeg" in cmd[0]:
            out_file = cmd[-1]
            out_path = RealPath(out_file)
            if not out_path.is_absolute():
                out_path = tmp_path / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.touch()
        return mock_res

    script_path = os.path.join(backend_dir, "clean_rebuild.py")
    with open(script_path, "r", encoding="utf-8") as f:
        code_content = f.read()

    # カバレッジ測定のためにコンパイル
    compiled_code = compile(code_content, script_path, "exec")

    with patch("pathlib.Path", mock_path_fn), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("progressive_preview.ProgressivePreview"), \
         patch("services.preview_report_generator.PreviewReportGenerator"):
         
        global_ns = {
            "__name__": "__main__",
            "__file__": script_path,
        }
        
        exec(compiled_code, global_ns)

# __main__ ブロックの実行テスト (失敗パターン)
def test_main_execution_failed(tmp_path):
    mock_path_fn = get_path_patch(tmp_path)
    
    raw_dir = tmp_path / "raw_videos" / "AI Studio アップロード用動画"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "シーン01_前編.mp4").touch()
    (raw_dir / "シーン02_ゲスト書道.mp4").touch()
    (raw_dir / "シーン03_後編01.mp4").touch()
    (raw_dir / "シーン04_後編02.mp4").touch()
    
    logo_path = tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    create_dummy_png(logo_path)
    
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 0
        if "ffprobe" in cmd[0]:
            mock_res.stdout = "1800.0"
        elif "ffmpeg" in cmd[0]:
            out_file = cmd[-1]
            # 最終成果物を touch しないことで失敗させる
            if "soul_narrative_CLEAN_FINAL.mp4" not in out_file:
                out_path = RealPath(out_file)
                if not out_path.is_absolute():
                    out_path = tmp_path / out_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.touch()
        return mock_res

    script_path = os.path.join(backend_dir, "clean_rebuild.py")
    with open(script_path, "r", encoding="utf-8") as f:
        code_content = f.read()

    # カバレッジ測定のためにコンパイル
    compiled_code = compile(code_content, script_path, "exec")

    with patch("pathlib.Path", mock_path_fn), \
         patch("subprocess.run", side_effect=mock_subprocess_run), \
         patch("progressive_preview.ProgressivePreview"), \
         patch("services.preview_report_generator.PreviewReportGenerator"):
         
        global_ns = {
            "__name__": "__main__",
            "__file__": script_path,
        }
        
        exec(compiled_code, global_ns)
