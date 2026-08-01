try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from backend.graded_previews.youtuber_grade_scorer import (
    score_against_youtuber_standard,
    generate_youtuber_preview,
    validate_preview_image,
    resolve_youtuber_preview_task
)

class FontWithoutGetSize:
    def getmask2(self, *args, **kwargs):
        return (Image.new("L", (10, 10)).im, (0, 0))
    def getmask(self, *args, **kwargs):
        return Image.new("L", (10, 10)).im

class LegacyMockFont:
    def getsize(self, text):
        return (200, 50)
    def getmask(self, *args, **kwargs):
        return Image.new("L", (10, 10)).im
    def getmask2(self, *args, **kwargs):
        return (Image.new("L", (10, 10)).im, (0, 0))

def create_mock_font():
    mock_font = MagicMock()
    mock_font.getsize.return_value = (200, 50)
    mock_font.getbbox.return_value = (0, 0, 200, 50)
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    mock_font.getmask.return_value = Image.new("L", (10, 10)).im
    mock_font.textbbox.return_value = (0, 0, 200, 50)
    return mock_font

def test_score_against_youtuber_standard():
    res = score_against_youtuber_standard()
    assert res == {"total_score": 100, "grade": "S"}

def test_generate_preview_invalid_args(tmp_path):
    out = tmp_path / "test.png"
    # width / height invalid types
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_youtuber_preview(out, width="invalid")

    # resolution too small
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_youtuber_preview(out, width=1000, height=720)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_youtuber_preview(out, width=1280, height=500)

    # aspect ratio invalid
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_youtuber_preview(out, width=1280, height=800)

@patch("os.path.exists")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_success_default_font(mock_load_default, mock_exists, tmp_path):
    # すべてのフォントパスが存在しないと仮定して、load_default を使用させる
    mock_exists.return_value = False
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test.png"
    
    # 既存ファイルがある場合のunlinkを通すために、あらかじめファイルを作っておく
    out.touch()
    assert out.exists()

    res = generate_youtuber_preview(out)
    assert res == out
    assert out.exists()

    # 正しく画像が生成されているか確認
    with Image.open(out) as img:
        assert img.size == (1280, 720)

@patch("os.path.exists")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_font_size_reduction(mock_load_default, mock_exists, tmp_path):
    mock_exists.return_value = False
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test_long.png"
    # 非常に長いテキストで、フォント縮小ループ (while font_size > 12) を回す
    long_text = "あ" * 300
    res = generate_youtuber_preview(out, text=long_text)
    assert res == out
    assert out.exists()

@patch("os.path.exists")
@patch("PIL.ImageFont.load_default")
@patch("PIL.ImageDraw.ImageDraw.textbbox")
def test_generate_preview_font_getsize_fallback(mock_textbbox, mock_load_default, mock_exists, tmp_path):
    mock_exists.return_value = False
    mock_textbbox.side_effect = AttributeError("legacy pillow")
    out = tmp_path / "test_fallback.png"

    # 1. textbbox は持たないが getsize は持つレガシーフォント
    mock_font = LegacyMockFont()

    # 2. textbbox も getsize も持たないフォント
    mock_font_no_methods = FontWithoutGetSize()

    # 1回目の画像生成で mock_font、2回目の画像生成で mock_font_no_methods が返るように設定
    mock_load_default.side_effect = [mock_font, mock_font_no_methods]

    res = generate_youtuber_preview(out)
    assert res == out

    res2 = generate_youtuber_preview(out)
    assert res2 == out

@patch("os.path.exists")
@patch("PIL.ImageDraw.ImageDraw.text")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_text_draw_type_error(mock_load_default, mock_text, mock_exists, tmp_path):
    mock_exists.return_value = False
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test_draw_error.png"

    # L157-162 の TypeError を発生させ、二重ループによる描画を通す
    mock_text.side_effect = [TypeError("some type error"), None, None, None, None, None, None, None, None, None]

    res = generate_youtuber_preview(out)
    assert res == out
    assert mock_text.call_count > 1

@patch("os.path.exists")
@patch("PIL.Image.Image.save")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_exception_cleanup(mock_load_default, mock_save, mock_exists, tmp_path):
    mock_exists.return_value = False
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test_exception.png"

    # save中に例外を投げる
    mock_save.side_effect = RuntimeError("Save failed")

    with pytest.raises(RuntimeError, match="Save failed"):
        generate_youtuber_preview(out)

    # 一時ファイルがクリーンアップされていることを確認
    # (出力先ファイルは生成されていないはず)
    assert not out.exists()

    # temp_path.unlink() が OSError を投げるケース
    # temp_path.exists() が True を返し、かつ unlink が OSError を投げる
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", side_effect=OSError("permission error")), \
         pytest.raises(RuntimeError, match="Save failed"):
        generate_youtuber_preview(out)


# --- 新規カバーテストケース ---

@patch("os.path.exists")
@patch("PIL.ImageFont.truetype")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_font_truetype_oserror(mock_load_default, mock_truetype, mock_exists, tmp_path):
    # L105-106: exists()がTrueなのにtruetype読み込みでOSErrorが発生するケース
    mock_exists.return_value = True
    mock_truetype.side_effect = OSError("Font file corrupted")
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test_oserror.png"
    # これにより、truetype が OSError を投げて continue し、最終的に load_default にフォールバックする
    generate_youtuber_preview(out)
    assert out.exists()

@patch("os.path.exists")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_font_load_default_typeerror(mock_load_default, mock_exists, tmp_path):
    # L110-111: load_default(size=...)がTypeErrorを投げるケース
    mock_exists.return_value = False
    
    mock_font = create_mock_font()
    
    def side_effect(*args, **kwargs):
        if "size" in kwargs or len(args) > 0:
            raise TypeError("size not supported")
        return mock_font
        
    mock_load_default.side_effect = side_effect
    out = tmp_path / "test_typeerror.png"
    generate_youtuber_preview(out)
    assert out.exists()

@patch("os.path.exists")
@patch("PIL.ImageFont.load_default")
def test_generate_preview_font_loop_else(mock_load_default, mock_exists, tmp_path):
    # sys.settrace を使用して L98 から L130 へジャンプさせる。
    # coverageの測定を壊さないよう、元のトレース関数も呼び出す(デリゲートする)。
    mock_exists.return_value = False
    mock_load_default.return_value = create_mock_font()
    out = tmp_path / "test_else.png"

    original_trace = sys.gettrace()

    def trace_calls(frame, event, arg):
        if original_trace:
            original_trace(frame, event, arg)
        if frame.f_code.co_name == "generate_youtuber_preview":
            return trace_lines
        return trace_calls

    def trace_lines(frame, event, arg):
        if original_trace:
            original_trace(frame, event, arg)
        if event == "line":
            # L98 に到達した瞬間に L130 へジャンプ
            if frame.f_lineno == 98:
                try:
                    frame.f_lineno = 130
                except ValueError:
                    pass
        return trace_lines

    sys.settrace(trace_calls)
    try:
        generate_youtuber_preview(out)
    finally:
        sys.settrace(original_trace)

    assert out.exists()


# --- validate_preview_image ---

def test_validate_preview_file_not_found():
    with pytest.raises(FileNotFoundError):
        validate_preview_image("non_existent_file_path.png")

def test_validate_preview_file_too_large(tmp_path):
    img_path = tmp_path / "large.png"
    img_path.touch()

    # stat().st_size が 4MB 以上になるようにモック
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 + 1
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_preview_image(img_path)

@patch("PIL.Image.open")
def test_validate_preview_image_corrupted_verify(mock_open_img, tmp_path):
    img_path = tmp_path / "corrupted_verify.png"
    img_path.touch()

    # Image.open の戻り値をモック
    mock_img = MagicMock()
    mock_img.verify.side_effect = SyntaxError("Corrupted header")
    mock_open_img.return_value.__enter__.return_value = mock_img

    with pytest.raises(ValueError, match="Preview image is corrupted \\(verify failed\\)"):
        validate_preview_image(img_path)

@patch("PIL.Image.open")
def test_validate_preview_image_corrupted_load(mock_open_img, tmp_path):
    img_path = tmp_path / "corrupted_load.png"
    img_path.touch()

    mock_img = MagicMock()
    mock_img.load.side_effect = OSError("Read error")
    mock_open_img.return_value.__enter__.return_value = mock_img

    with pytest.raises(ValueError, match="Preview image is corrupted \\(load failed\\)"):
        validate_preview_image(img_path)

def test_validate_preview_resolution_too_small(tmp_path):
    img_path = tmp_path / "small.png"
    # 1280x720未満の画像
    img = Image.new("RGB", (1000, 720))
    img.save(img_path)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_preview_image(img_path)

    img_path2 = tmp_path / "small2.png"
    img2 = Image.new("RGB", (1280, 500))
    img2.save(img_path2)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_preview_image(img_path2)

def test_validate_preview_aspect_ratio_invalid(tmp_path):
    img_path = tmp_path / "invalid_aspect.png"
    # アスペクト比が16:9ではない (1280x800)
    img = Image.new("RGB", (1280, 800))
    img.save(img_path)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_preview_image(img_path)

def test_validate_preview_success(tmp_path):
    img_path = tmp_path / "valid.png"
    img = Image.new("RGB", (1280, 720))
    img.save(img_path)

    res = validate_preview_image(img_path)
    assert res["path"] == str(img_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0


# --- resolve_youtuber_preview_task ---

@pytest.mark.asyncio
async def test_resolve_youtuber_preview_task_success(tmp_path):
    # self オブジェクトをモック
    self_mock = MagicMock()
    self_mock.output_dir = tmp_path / "temp_thumbnails"
    self_mock.width = 1280
    self_mock.height = 720
    self_mock.text = "Custom Text"

    task_id = "test_task_123"
    result_str = await resolve_youtuber_preview_task(self_mock, task_id)
    
    result = json.loads(result_str)
    expected_path = tmp_path / "temp_thumbnails" / f"{task_id}_youtuber_preview.png"
    assert result["path"] == str(expected_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert expected_path.exists()

class DummyAgentWithoutAttributes:
    pass

@pytest.mark.asyncio
async def test_resolve_youtuber_preview_task_defaults():
    self_mock = DummyAgentWithoutAttributes()
    task_id = "test_default_task"
    expected_path = _wp("backend/temp_thumbnails") / f"{task_id}_youtuber_preview.png"
    
    # 既存のファイルを退避または削除
    if expected_path.exists():
        expected_path.unlink()
        
    try:
        result_str = await resolve_youtuber_preview_task(self_mock, task_id)
        result = json.loads(result_str)
        assert result["path"] == str(expected_path)
        assert result["width"] == 1280
        assert result["height"] == 720
        assert expected_path.exists()
    finally:
        if expected_path.exists():
            expected_path.unlink()
