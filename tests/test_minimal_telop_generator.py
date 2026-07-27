import os
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageFont, ImageDraw

from backend.minimal_telop_generator import MinimalTelopGenerator, generate_all_theme_telops


def test_init_creates_directory(tmp_path):
    output_dir = tmp_path / "test_telops"
    assert not output_dir.exists()
    
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    assert generator.output_dir == output_dir
    assert output_dir.exists()


def test_get_font_success():
    generator = MinimalTelopGenerator()
    
    # 最初のフォントが存在し、読み込みに成功する場合
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch.object(Path, "exists", return_value=True), \
         patch("PIL.ImageFont.truetype", return_value=mock_font) as mock_truetype:
        
        font = generator._get_font(24)
        assert font == mock_font
        mock_truetype.assert_called_once_with(generator.font_paths[0], 24)


def test_get_font_fallback_on_exception():
    generator = MinimalTelopGenerator()
    
    # 最初のフォントは存在するが例外が発生し、2番目のフォントで成功する場合
    mock_font2 = MagicMock(spec=ImageFont.FreeTypeFont)
    
    def side_effect(path, size):
        if path == generator.font_paths[0]:
            raise OSError("Invalid font file")
        return mock_font2

    with patch.object(Path, "exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype:
        
        font = generator._get_font(20)
        assert font == mock_font2
        assert mock_truetype.call_count == 2


def test_get_font_fallback_to_default():
    generator = MinimalTelopGenerator()
    
    # すべてのフォントが存在しない場合
    with patch.object(Path, "exists", return_value=False), \
         patch("PIL.ImageFont.load_default") as mock_load_default:
        
        generator._get_font(16)
        mock_load_default.assert_called_once()


def test_generate_minimal_telop_success(tmp_path):
    output_dir = tmp_path / "telops"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    output_path = output_dir / "test_telop.png"
    
    theme_text = "テストテキスト"
    res_path = generator.generate_minimal_telop(
        theme_text=theme_text,
        output_path=str(output_path),
        font_size=16,
        padding=8
    )
    
    assert res_path == str(output_path)
    assert output_path.exists()
    
    # 画像を開いて検証
    with Image.open(output_path) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"
        # 画像サイズが padding 分より大きいことを確認
        assert img.width > 16
        assert img.height > 16


def test_generate_minimal_telop_empty_text(tmp_path):
    output_dir = tmp_path / "telops"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    output_path = output_dir / "empty_telop.png"
    
    with pytest.raises(ValueError, match="theme_text cannot be empty."):
        generator.generate_minimal_telop(
            theme_text="",
            output_path=str(output_path),
            font_size=12,
            padding=4
        )


def test_generate_all_theme_telops(tmp_path):
    # generate_all_theme_telops 内で作成される MinimalTelopGenerator の output_dir を tmp_path に変更する
    original_init = MinimalTelopGenerator.__init__
    
    def mock_init(self, output_dir="backend/temp/minimal_telops"):
        original_init(self, output_dir=str(tmp_path / "minimal_telops"))

    with patch.object(MinimalTelopGenerator, "__init__", mock_init):
        generated = generate_all_theme_telops()
        
        assert len(generated) > 0
        for theme, path in generated.items():
            assert Path(path).exists()
            assert Path(path).suffix == ".png"


def test_main_block(tmp_path):
    original_init = MinimalTelopGenerator.__init__
    
    def mock_init(self, output_dir="backend/temp/minimal_telops"):
        original_init(self, output_dir=str(tmp_path / "minimal_telops_main"))

    with patch.object(MinimalTelopGenerator, "__init__", mock_init), \
         patch("builtins.print") as mock_print:
        
        runpy.run_module("backend.minimal_telop_generator", run_name="__main__")
        assert mock_print.called


def test_get_font_all_fonts_throw_exception():
    generator = MinimalTelopGenerator()
    
    # すべてのフォントパスで ImageFont.truetype が例外を投げる場合
    with patch.object(Path, "exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=OSError("Font error")), \
         patch("PIL.ImageFont.load_default") as mock_load_default:
        
        generator._get_font(16)
        mock_load_default.assert_called_once()


def test_generate_minimal_telop_large_values(tmp_path):
    output_dir = tmp_path / "telops_large"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    output_path = output_dir / "large_telop.png"
    
    theme_text = "とても長いテーマテキストのテストケースです。フォントサイズとパディングを大きくしたときの挙動を確認します。"
    res_path = generator.generate_minimal_telop(
        theme_text=theme_text,
        output_path=str(output_path),
        font_size=64,
        padding=40
    )
    
    assert res_path == str(output_path)
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        assert img.width > 100
        assert img.height > 100


def test_draw_rounded_rectangle_edge_cases():
    generator = MinimalTelopGenerator()
    
    # テスト用のキャンバス作成
    img = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 1. corner_radius = 0 の場合
    # エラーが発生せずに実行できることを確認
    generator._draw_rounded_rectangle(draw, (10, 10, 90, 90), corner_radius=0, fill=(255, 255, 255, 255))
    
    # 2. corner_radius が限界値（幅/2 または 高さ/2）の場合 (80 / 2 = 40)
    # エラーが発生せずに実行できることを確認
    generator._draw_rounded_rectangle(draw, (10, 10, 90, 90), corner_radius=40, fill=(255, 255, 255, 255))

    # 3. corner_radius が大きすぎる場合 (50)
    # クリッピング安全策が走り、エラーにならずに実行できることを検証
    generator._draw_rounded_rectangle(draw, (10, 10, 90, 90), corner_radius=50, fill=(255, 255, 255, 255))


def test_generate_minimal_telop_multiline(tmp_path):
    output_dir = tmp_path / "telops_multiline"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    output_path = output_dir / "multiline.png"
    
    theme_text = "一行目\n二行目\n三行目"
    res_path = generator.generate_minimal_telop(
        theme_text=theme_text,
        output_path=str(output_path),
        font_size=16,
        padding=8
    )
    assert res_path == str(output_path)
    assert output_path.exists()
    
    with Image.open(output_path) as img:
        assert img.width > 0
        assert img.height > 0


def test_generate_minimal_telop_emoji(tmp_path):
    output_dir = tmp_path / "telops_emoji"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    output_path = output_dir / "emoji.png"
    
    theme_text = "テーマ🎥✨"
    res_path = generator.generate_minimal_telop(
        theme_text=theme_text,
        output_path=str(output_path),
        font_size=16,
        padding=8
    )
    assert res_path == str(output_path)
    assert output_path.exists()


def test_generate_minimal_telop_edge_dimensions(tmp_path):
    output_dir = tmp_path / "telops_dimensions"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    
    # パディング 0
    output_path_p0 = output_dir / "padding_0.png"
    res_p0 = generator.generate_minimal_telop(
        theme_text="テスト",
        output_path=str(output_path_p0),
        font_size=16,
        padding=0
    )
    assert res_p0 == str(output_path_p0)
    assert output_path_p0.exists()
    
    # フォントサイズ 1
    output_path_f1 = output_dir / "font_1.png"
    res_f1 = generator.generate_minimal_telop(
        theme_text="テスト",
        output_path=str(output_path_f1),
        font_size=1,
        padding=4
    )
    assert res_f1 == str(output_path_f1)
    assert output_path_f1.exists()


def test_init_creates_nested_directory(tmp_path):
    output_dir = tmp_path / "nested" / "deep" / "dir"
    assert not output_dir.exists()
    
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    assert generator.output_dir == output_dir
    assert output_dir.exists()


def test_generate_minimal_telop_invalid_params(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_invalid.png")
    
    # font_size <= 0
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=0)
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=-5)
        
    # font_size > 200
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=201)
        
    # padding < 0
    with pytest.raises(ValueError, match="Invalid padding."):
        generator.generate_minimal_telop("Test", output_file, padding=-1)
        
    # padding > 100
    with pytest.raises(ValueError, match="Invalid padding."):
        generator.generate_minimal_telop("Test", output_file, padding=101)


def test_generate_minimal_telop_font_fallback_getsize(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_fallback_getsize.png")
    
    mock_font = MagicMock()
    del mock_font.getbbox
    mock_font.getsize.return_value = (50, 20)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch.object(generator, "_get_font", return_value=mock_font):
        res = generator.generate_minimal_telop("Test", output_file)
        assert res == output_file
        assert Path(output_file).exists()


def test_generate_minimal_telop_font_fallback_no_methods(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_fallback_no_methods.png")
    
    mock_font = MagicMock()
    del mock_font.getbbox
    del mock_font.getsize
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch.object(generator, "_get_font", return_value=mock_font):
        res = generator.generate_minimal_telop("Test", output_file, font_size=16)
        assert res == output_file
        assert Path(output_file).exists()


def test_generate_minimal_telop_font_fallback_exception(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_fallback_exception.png")
    
    mock_font = MagicMock()
    mock_font.getbbox.side_effect = TypeError("Mock type error")
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch.object(generator, "_get_font", return_value=mock_font):
        res = generator.generate_minimal_telop("Test", output_file, font_size=16)
        assert res == output_file
        assert Path(output_file).exists()



def test_draw_rounded_rectangle_fallback(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    
    img = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    class LegacyDraw:
        def __init__(self, d):
            self._d = d
        def rectangle(self, xy, fill=None, outline=None, width=1):
            self._d.rectangle(xy, fill=fill, outline=outline, width=width)
        def ellipse(self, xy, fill=None, outline=None, width=1):
            self._d.ellipse(xy, fill=fill, outline=outline, width=width)
            
    legacy_draw = LegacyDraw(draw)
    
    # corner_radius = 5 の場合
    generator._draw_rounded_rectangle(legacy_draw, (10, 10, 90, 90), corner_radius=5, fill=(255, 255, 255, 255))
    
    # corner_radius = 0 の場合
    generator._draw_rounded_rectangle(legacy_draw, (10, 10, 90, 90), corner_radius=0, fill=(255, 255, 255, 255))

