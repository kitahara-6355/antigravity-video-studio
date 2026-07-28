import pytest
import json
from pathlib import Path
from PIL import Image, ImageFont, ImageDraw
from unittest.mock import patch, MagicMock
from path_resolver import project_root
from backend.add_simple_branding import (
    _get_lanczos_filter,
    _resolve_branding_paths,
    _load_and_resize_logo,
    _select_branding_font,
    _create_telop_image,
    create_combined_branding,
    add_branding_to_video,
    _validate_thumbnail_params,
    _generate_gradient_background,
    _draw_decorations,
    _wrap_text_lines,
    _fit_text_font,
    _draw_wrapped_text,
    _save_thumbnail_to_path,
    _generate_preview_if_needed,
    generate_simple_branding_thumbnail,
    validate_thumbnail,
    resolve_branding_task,
)

def test_get_lanczos_filter():
    class MockImgModuleWithResampling:
        class Resampling:
            LANCZOS = 999
    
    assert _get_lanczos_filter(MockImgModuleWithResampling) == 999

    class MockImgModuleWithLanczos:
        LANCZOS = 888

    assert _get_lanczos_filter(MockImgModuleWithLanczos) == 888

    class MockImgModuleWithAntialias:
        ANTIALIAS = 777

    assert _get_lanczos_filter(MockImgModuleWithAntialias) == 777

    class MockImgModuleWithBicubic:
        BICUBIC = 666

    assert _get_lanczos_filter(MockImgModuleWithBicubic) == 666

    class MockImgModuleEmpty:
        pass

    assert _get_lanczos_filter(MockImgModuleEmpty) is None


def test_resolve_branding_paths(tmp_path):
    logo_path, output_path = _resolve_branding_paths(tmp_path)
    
    assert logo_path == tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    assert output_path == tmp_path / "backend" / "branding" / "final_branding.png"
    assert output_path.parent.exists()

    # base_path 未指定なら project_root() 配下に落ちること。
    # 以前は "video-automation" という旧リポジトリ名が含まれることを見ていたが、
    # それは直書きされた絶対パスの一部を見ていただけで、リポジトリ名が
    # 変わった時点で「たまたま通っている」状態になっていた。
    logo_path_none, output_path_none = _resolve_branding_paths(None)
    assert logo_path_none == project_root() / "backend" / "branding" / "logos" / "brand_logo.png"


def test_load_and_resize_logo(tmp_path):
    logo_path = tmp_path / "brand_logo.png"
    
    fallback_logo = _load_and_resize_logo(logo_path, 100, 50)
    assert fallback_logo.size == (100, 50)
    assert fallback_logo.mode == "RGBA"
    pixel = fallback_logo.getpixel((0, 0))
    assert pixel == (200, 50, 50, 255)

    dummy_logo = Image.new("RGBA", (200, 200), (0, 255, 0, 255))
    dummy_logo.save(logo_path)
    
    resized_logo = _load_and_resize_logo(logo_path, 50, 50)
    assert resized_logo.size == (50, 50)
    assert resized_logo.mode == "RGBA"


def test_select_branding_font():
    font = _select_branding_font(18)
    assert isinstance(font, (ImageFont.ImageFont, ImageFont.FreeTypeFont))


def test_create_telop_image():
    font = _select_branding_font(18)
    telop_img = _create_telop_image("テストテロップ", 300, 50, font)
    assert telop_img.size == (300, 50)
    assert telop_img.mode == "RGBA"
    pixel = telop_img.getpixel((0, 0))
    assert pixel == (0, 0, 0, 128)


def test_create_combined_branding(tmp_path):
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    
    logo_path = logo_dir / "brand_logo.png"
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(logo_path)
    
    output_path = create_combined_branding(target_height=45, base_path=tmp_path)
    
    assert output_path == tmp_path / "backend" / "branding" / "final_branding.png"
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        assert img.size == (331, 45)
        assert img.mode == "RGBA"

    with patch.object(Image.Image, "save", side_effect=OSError("Save failed")):
        with pytest.raises(OSError, match="Save failed"):
            create_combined_branding(target_height=45, base_path=tmp_path)


def test_add_branding_to_video():
    # Path.exists に autospec=True を指定して、self (Pathオブジェクト自身) を受け取るようにする
    with patch("backend.add_simple_branding.Path.exists", autospec=True) as mock_exists, \
         patch("backend.add_simple_branding.create_combined_branding") as mock_create_branding, \
         patch("backend.add_simple_branding.subprocess.run") as mock_run:
        
        def exists_side_effect(self_path):
            path_str = str(self_path)
            if "soul_narrative_FINAL_EDITED.mp4" in path_str or "soul_narrative_YOUTUBE_READY.mp4" in path_str:
                return True
            return False
            
        mock_exists.side_effect = exists_side_effect
        
        mock_create_branding.return_value = Path("dummy_branding.png")
        
        mock_ffprobe_result = MagicMock()
        mock_ffprobe_result.returncode = 0
        mock_ffprobe_result.stdout = "120.5\n"
        
        mock_ffmpeg_result = MagicMock()
        mock_ffmpeg_result.returncode = 0
        
        mock_run.side_effect = lambda cmd, **kwargs: mock_ffprobe_result if "ffprobe" in cmd[0] else mock_ffmpeg_result
        
        with patch("backend.add_simple_branding.Path.stat") as mock_stat:
            mock_stat_obj = MagicMock()
            mock_stat_obj.st_size = 1024 * 1024 * 10
            mock_stat.return_value = mock_stat_obj
            
            result_path = add_branding_to_video()
            assert result_path is not None
            assert "soul_narrative_YOUTUBE_READY.mp4" in str(result_path)

    with patch("backend.add_simple_branding.Path.exists", return_value=False):
        result_path = add_branding_to_video()
        assert result_path is None

    with patch("backend.add_simple_branding.Path.exists", autospec=True) as mock_exists, \
         patch("backend.add_simple_branding.create_combined_branding") as mock_create_branding, \
         patch("backend.add_simple_branding.subprocess.run") as mock_run:
        
        mock_exists.return_value = True
        mock_create_branding.return_value = Path("dummy_branding.png")
        
        mock_ffmpeg_result = MagicMock()
        mock_ffmpeg_result.returncode = 1
        mock_ffmpeg_result.stderr = "FFmpeg error"
        mock_run.return_value = mock_ffmpeg_result
        
        result_path = add_branding_to_video()
        assert result_path is None


def test_validate_thumbnail_params(tmp_path):
    w, h, out_path, suffix = _validate_thumbnail_params(tmp_path / "thumb.png", 1920, 1080)
    assert w == 1920
    assert h == 1080
    assert out_path == tmp_path / "thumb.png"
    assert suffix == ".png"

    with pytest.raises(ValueError, match="must be integers"):
        _validate_thumbnail_params(tmp_path / "thumb.png", "abc", 1080)
    
    with pytest.raises(ValueError, match="must be positive integers"):
        _validate_thumbnail_params(tmp_path / "thumb.png", 0, 1080)
        
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        _validate_thumbnail_params(tmp_path / "thumb.png", 640, 360)
        
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        _validate_thumbnail_params(tmp_path / "thumb.png", 8000, 4500)

    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        _validate_thumbnail_params(tmp_path / "thumb.png", 1920, 1200)

    with pytest.raises(ValueError, match="must be a file path, not a directory"):
        _validate_thumbnail_params(tmp_path, 1920, 1080)

    with pytest.raises(ValueError, match="Unsupported file format"):
        _validate_thumbnail_params(tmp_path / "thumb.bmp", 1920, 1080)


def test_generate_gradient_background():
    img = _generate_gradient_background(100, 100)
    assert img.size == (100, 100)
    assert img.mode == "RGBA"


def test_draw_decorations():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin, border_w = _draw_decorations(d, 100, 100, 200, 200, 2)
    assert margin > 0
    assert border_w > 0


def test_wrap_text_lines():
    lines = _wrap_text_lines("short text")
    assert lines == ["short text"]
    
    long_text = "a" * 70
    lines = _wrap_text_lines(long_text)
    assert len(lines) == 3
    assert lines[0] == "a" * 30
    assert lines[1] == "a" * 30
    assert lines[2] == "a" * 10


def test_fit_text_font():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    wrapped = ["test line"]
    font, size = _fit_text_font(d, wrapped, 150, 150, 24, 2)
    assert font is not None
    assert size <= 24


def test_draw_wrapped_text():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _select_branding_font(12)
    _draw_wrapped_text(d, ["test"], font, 12, 200, 200, 2)


def test_save_thumbnail_to_path(tmp_path):
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    temp_path = tmp_path / "temp.png"
    output_path = tmp_path / "out.png"
    
    for sfx in [".png", ".jpg", ".webp"]:
        out_img = _save_thumbnail_to_path(img, 100, 100, temp_path, output_path, sfx)
        assert out_img.size == (100, 100)
        assert out_img.mode == "RGB"
        assert output_path.exists()
        output_path.unlink()


def test_generate_preview_if_needed(tmp_path):
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    preview_path = tmp_path / "prev.png"
    temp_preview_path = tmp_path / "prev.tmp"
    
    _generate_preview_if_needed(img, preview_path, temp_preview_path)
    assert preview_path.exists()


def test_generate_simple_branding_thumbnail(tmp_path):
    output_path = tmp_path / "thumbnail.png"
    preview_path = tmp_path / "preview.png"
    
    res = generate_simple_branding_thumbnail(
        output_path=output_path,
        width=1280,
        height=720,
        text="Hello World\nLine2",
        preview_path=preview_path
    )
    assert res == output_path
    assert output_path.exists()
    assert preview_path.exists()
    
    output_path2 = tmp_path / "thumbnail2.png"
    generate_simple_branding_thumbnail(output_path=output_path2, width=1280, height=720, text=None)
    assert output_path2.exists()
    
    output_path3 = tmp_path / "thumbnail3.jpg"
    generate_simple_branding_thumbnail(output_path=output_path3, width=3840, height=2160)
    assert output_path3.exists()

    with pytest.raises(ValueError):
        generate_simple_branding_thumbnail(output_path=output_path, width=100, height=100)


def test_validate_thumbnail(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "non_existent.png")
        
    dummy_file = tmp_path / "dummy.png"
    Image.new("RGBA", (10, 10)).save(dummy_file)
    with patch("backend.add_simple_branding.Path.stat") as mock_stat:
        mock_stat_obj = MagicMock()
        mock_stat_obj.st_size = 5 * 1024 * 1024
        mock_stat.return_value = mock_stat_obj
        with pytest.raises(ValueError, match="exceeds 4MB limit"):
            validate_thumbnail(dummy_file)

    corrupt_file = tmp_path / "corrupt.png"
    with open(corrupt_file, "wb") as f:
        f.write(b"not an image data")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupt_file)

    small_file = tmp_path / "small.png"
    Image.new("RGB", (100, 100)).save(small_file)
    with pytest.raises(ValueError, match="Resolution must be at least"):
        validate_thumbnail(small_file)
        
    wrong_aspect_file = tmp_path / "wrong_aspect.png"
    Image.new("RGB", (1280, 1000)).save(wrong_aspect_file)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(wrong_aspect_file)

    valid_file = tmp_path / "valid.png"
    Image.new("RGB", (1280, 720)).save(valid_file)
    info = validate_thumbnail(valid_file)
    assert info["width"] == 1280
    assert info["height"] == 720
    
    valid_prev = tmp_path / "valid_prev.png"
    Image.new("RGB", (640, 360)).save(valid_prev)
    info_prev = validate_thumbnail(valid_prev, is_preview=True)
    assert info_prev["width"] == 640


@pytest.mark.asyncio
async def test_resolve_branding_task(tmp_path):
    class MockAgent:
        def __init__(self):
            self.width = 1280
            self.height = 720
            self.text = "Mock task text"
            self.output_dir = tmp_path
            
    agent = MockAgent()
    task_id = "test-task-123"
    
    result_json = await resolve_branding_task(agent, task_id)
    result = json.loads(result_json)
    
    assert "path" in result
    assert result["width"] == 1280
    assert result["height"] == 720
    assert "preview" in result
    assert result["preview"]["width"] == 640
    
    agent_no_text = MockAgent()
    agent_no_text.text = None
    result_json_no_text = await resolve_branding_task(agent_no_text, "test-task-456")
    result_no_text = json.loads(result_json_no_text)
    assert result_no_text["width"] == 1280

def test_resolve_branding_paths_exceptions():
    with patch("backend.add_simple_branding.Path.mkdir", side_effect=OSError("Permission denied")):
        logo_path, output_path = _resolve_branding_paths(Path("C:/dummy_path"))
        assert logo_path == Path("C:/dummy_path/backend/branding/logos/brand_logo.png")


def test_load_and_resize_logo_edge_cases(tmp_path):
    logo_path = tmp_path / "brand_logo.png"
    dummy_logo = Image.new("RGBA", (200, 200), (0, 255, 0, 255))
    dummy_logo.save(logo_path)

    with patch("backend.add_simple_branding.LANCZOS", None):
        resized_logo = _load_and_resize_logo(logo_path, 50, 50)
        assert resized_logo.size == (50, 50)

    # 描画時の例外を発生させるために、ImageDraw.Draw をモックして例外を発生させる
    non_existent_logo = tmp_path / "non_existent.png"
    mock_draw = MagicMock()
    mock_draw.text.side_effect = ValueError("Draw error")
    with patch("backend.add_simple_branding.ImageDraw.Draw", return_value=mock_draw):
        fallback = _load_and_resize_logo(non_existent_logo, 100, 50)
        assert fallback.size == (100, 50)


def test_select_branding_font_exceptions():
    from PIL import ImageFont as PILImageFont
    real_truetype = PILImageFont.truetype
    
    def mock_truetype(font, size, *args, **kwargs):
        if any(x in str(font) for x in ["msgothic", "msmincho", "meiryo", "Hiragino", "truetype", "noto"]):
            raise OSError("Load error")
        return real_truetype(font, size, *args, **kwargs)

    with patch("backend.add_simple_branding.Path.exists", return_value=True),          patch("backend.add_simple_branding.ImageFont.truetype", side_effect=mock_truetype):
        font = _select_branding_font(18)
        assert font is not None

    with patch("backend.add_simple_branding.Path.exists", return_value=True),          patch("backend.add_simple_branding.ImageFont.truetype", side_effect=mock_truetype),          patch("backend.add_simple_branding.ImageFont.load_default", side_effect=Exception("No font at all")):
        with pytest.raises(Exception, match="No font at all"):
            _select_branding_font(18)


def test_validate_thumbnail_params_mkdir_exception(tmp_path):
    with patch("backend.add_simple_branding.Path.mkdir", side_effect=TypeError("Mkdir error")):
        w, h, out_path, suffix = _validate_thumbnail_params(tmp_path / "thumb.png", 1920, 1080)
        assert w == 1920


def test_fit_text_font_and_draw_bbox_exceptions():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    wrapped = ["test line"]
    
    # プロダクションコードの catch (OSError, ValueError) に合わせるため OSError を投げる
    with patch("backend.add_simple_branding.ImageFont.truetype", side_effect=OSError("Load error")),          patch("backend.add_simple_branding.ImageFont.load_default", side_effect=OSError("No default")):
        font, size = _fit_text_font(d, wrapped, 150, 150, 24, 2)
        assert font is None
        
    font = _select_branding_font(12)
    # ImageDraw.Draw.textbbox ではなく PIL.ImageDraw.ImageDraw.textbbox をパッチする
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=ValueError("Bbox error")):
        font_res, size_res = _fit_text_font(d, wrapped, 150, 150, 24, 2)
        assert size_res <= 24
        
        _draw_wrapped_text(d, wrapped, font, 12, 200, 200, 2)


def test_save_thumbnail_and_preview_lanczos_none_and_unlink_exceptions(tmp_path):
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    temp_path = tmp_path / "temp.png"
    output_path = tmp_path / "out.png"
    
    with patch("backend.add_simple_branding.LANCZOS", None):
        out_img = _save_thumbnail_to_path(img, 100, 100, temp_path, output_path, ".png")
        assert out_img.size == (100, 100)
        
        preview_path = tmp_path / "prev.png"
        temp_prev = tmp_path / "prev.tmp"
        _generate_preview_if_needed(out_img, preview_path, temp_prev)
        assert preview_path.exists()
        
    Image.new("RGBA", (100, 100)).save(output_path)
    # Windowsでrenameが既存ファイル上書きに失敗するのを防ぐためrenameをパッチ
    with patch("backend.add_simple_branding.Path.unlink", side_effect=OSError("Cannot delete")),          patch("backend.add_simple_branding.Path.rename") as mock_rename:
        out_img = _save_thumbnail_to_path(img, 100, 100, temp_path, output_path, ".png")
        assert out_img.size == (100, 100)
        assert mock_rename.called
        
        Image.new("RGBA", (100, 100)).save(preview_path)
        with patch("backend.add_simple_branding.Path.unlink", side_effect=OSError("Cannot delete")),              patch("backend.add_simple_branding.Path.rename") as mock_rename_prev:
            _generate_preview_if_needed(out_img, preview_path, temp_prev)
            assert mock_rename_prev.called


def test_generate_thumbnail_mkdir_exception_and_error_cleanup(tmp_path):
    output_path = tmp_path / "thumb.png"
    # mkdir失敗時にファイル保存できるように親ディレクトリをtmp_path直下(作成済み)にする
    preview_path = tmp_path / "prev.png"
    
    with patch("backend.add_simple_branding.Path.mkdir", side_effect=TypeError("Mkdir type error")):
        generate_simple_branding_thumbnail(output_path, 1280, 720, text="Test", preview_path=preview_path)
        assert output_path.exists()
        
    with patch("backend.add_simple_branding._save_thumbnail_to_path", side_effect=ValueError("Save error")):
        with pytest.raises(ValueError, match="Save error"):
            generate_simple_branding_thumbnail(output_path, 1280, 720, text="Test", preview_path=preview_path)


def test_validate_thumbnail_load_corrupt_and_preview_size(tmp_path):
    dummy_file = tmp_path / "dummy.png"
    Image.new("RGB", (1280, 720)).save(dummy_file)
    
    with patch.object(Image.Image, "load", side_effect=OSError("Load error")):
        with pytest.raises(ValueError, match="Image is corrupted"):
            validate_thumbnail(dummy_file)
            
    small_prev = tmp_path / "small_prev.png"
    Image.new("RGB", (200, 100)).save(small_prev)
    with pytest.raises(ValueError, match="Preview resolution must be at least"):
        validate_thumbnail(small_prev, is_preview=True)


def test_main_block_via_subprocess():
    import subprocess
    import sys
    cmd = [sys.executable, "backend/add_simple_branding.py"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0


def test_validate_thumbnail_preview_resolution_error(tmp_path):
    invalid_prev = tmp_path / "invalid_prev.png"
    Image.new("RGB", (300, 150)).save(invalid_prev)
    with pytest.raises(ValueError, match="Preview resolution must be at least"):
        validate_thumbnail(invalid_prev, is_preview=True)


def test_load_and_resize_logo_no_lanczos(tmp_path):
    logo_path = tmp_path / "brand_logo.png"
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(logo_path)
    with patch("backend.add_simple_branding.LANCZOS", None):
        logo = _load_and_resize_logo(logo_path, 50, 50)
        assert logo.size == (50, 50)


def test_save_thumbnail_to_path_unlink_error(tmp_path):
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    temp_path = tmp_path / "temp.png"
    output_path = tmp_path / "out.png"
    Image.new("RGB", (100, 100)).save(output_path)
    
    with patch("backend.add_simple_branding.Path.unlink", side_effect=OSError("Unlink failed")),          patch("backend.add_simple_branding.Path.rename") as mock_rename:
        out_img = _save_thumbnail_to_path(img, 100, 100, temp_path, output_path, ".png")
        assert out_img.size == (100, 100)
        mock_rename.assert_called_once()


def test_generate_preview_if_needed_unlink_error(tmp_path):
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    preview_path = tmp_path / "prev.png"
    temp_preview_path = tmp_path / "prev.tmp"
    Image.new("RGB", (100, 100)).save(preview_path)
    
    with patch("backend.add_simple_branding.Path.unlink", side_effect=OSError("Unlink failed")),          patch("backend.add_simple_branding.Path.rename") as mock_rename:
        _generate_preview_if_needed(img, preview_path, temp_preview_path)
        mock_rename.assert_called_once()


def test_validate_thumbnail_params_mkdir_error(tmp_path):
    with patch("backend.add_simple_branding.Path.mkdir", side_effect=OSError("Mkdir failed")):
        w, h, out_path, suffix = _validate_thumbnail_params(tmp_path / "thumb.png", 1920, 1080)
        assert w == 1920


def test_fit_text_font_textbbox_error():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    wrapped = ["test line"]
    
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=ValueError("textbbox error")):
        font, size = _fit_text_font(d, wrapped, 150, 150, 24, 2)
        assert font is not None
        assert size <= 24


def test_draw_wrapped_text_textbbox_error():
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _select_branding_font(12)
    
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=ValueError("textbbox error")):
        _draw_wrapped_text(d, ["test"], font, 12, 200, 200, 2)


def test_generate_simple_branding_thumbnail_cleanup_on_error(tmp_path):
    output_path = tmp_path / "thumbnail_error.png"
    
    with patch("backend.add_simple_branding._generate_gradient_background", side_effect=ValueError("Simulated error")):
        with pytest.raises(ValueError, match="Simulated error"):
            generate_simple_branding_thumbnail(
                output_path=output_path,
                width=1280,
                height=720,
                text="Test error path",
                preview_path=tmp_path / "prev_error.png"
            )


def test_save_thumbnail_to_path_no_lanczos_resampling_error(tmp_path):
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    temp_path = tmp_path / "temp.png"
    output_path = tmp_path / "out.png"
    
    class ImageWrapper:
        def __init__(self, real_module):
            self._real = real_module
        def __getattr__(self, name):
            if name == "Resampling":
                raise AttributeError("Resampling missing")
            return getattr(self._real, name)
            
    with patch("backend.add_simple_branding.LANCZOS", None),          patch("backend.add_simple_branding.Image", ImageWrapper(Image)):
        out_img = _save_thumbnail_to_path(img, 100, 100, temp_path, output_path, ".png")
        assert out_img.size == (100, 100)


def test_generate_preview_if_needed_no_lanczos_resampling_error(tmp_path):
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    preview_path = tmp_path / "prev.png"
    temp_preview_path = tmp_path / "prev.tmp"
    
    class ImageWrapper:
        def __init__(self, real_module):
            self._real = real_module
        def __getattr__(self, name):
            if name == "Resampling":
                raise AttributeError("Resampling missing")
            return getattr(self._real, name)
            
    with patch("backend.add_simple_branding.LANCZOS", None),          patch("backend.add_simple_branding.Image", ImageWrapper(Image)):
        _generate_preview_if_needed(img, preview_path, temp_preview_path)
        assert preview_path.exists()


def test_generate_simple_branding_thumbnail_cleanup_unlink_error(tmp_path):
    output_path = tmp_path / "thumbnail_cleanup_err.png"
    
    with patch("backend.add_simple_branding._generate_gradient_background", side_effect=ValueError("Simulated error")),          patch("backend.add_simple_branding.Path.unlink", side_effect=OSError("Unlink failed")):
        with pytest.raises(ValueError, match="Simulated error"):
            generate_simple_branding_thumbnail(
                output_path=output_path,
                width=1280,
                height=720,
                text="Test error cleanup"
            )


def test_validate_thumbnail_corrupt_load(tmp_path):
    valid_file = tmp_path / "valid.png"
    Image.new("RGB", (1280, 720)).save(valid_file)
    
    with patch("PIL.Image.Image.load", side_effect=OSError("Load failed")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(valid_file)
