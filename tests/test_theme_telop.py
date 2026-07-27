import os
from pathlib import Path
import pytest
from unittest import mock
from PIL import Image, ImageFont
from backend.theme_telop import ThemeTelopGenerator, main

def test_init_default(tmp_path):
    # output_dirを指定して初期化
    output_dir = tmp_path / "test_output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    assert generator.output_dir == output_dir
    assert output_dir.exists()
    assert len(generator.font_paths) > 0

def test_get_font_success():
    generator = ThemeTelopGenerator()
    font = generator._get_font(size=20)
    assert font is not None

def test_get_font_fallback():
    generator = ThemeTelopGenerator()
    generator.font_paths = ["C:/Windows/Fonts/NonExistentFont.ttf"]
    with mock.patch("PIL.ImageFont.load_default") as mock_load_default:
        generator._get_font(size=20)
        mock_load_default.assert_called_once()

def test_get_font_exception():
    generator = ThemeTelopGenerator()
    # Path.exists が True を返すようにモックし、存在するフォントファイルとして処理を進めさせる
    with mock.patch("pathlib.Path.exists", return_value=True):
        # ImageFont.truetypeが例外を投げるようにモックする
        with mock.patch("PIL.ImageFont.truetype", side_effect=OSError("Load error")):
            with mock.patch("PIL.ImageFont.load_default") as mock_load_default:
                generator._get_font(size=20)
                mock_load_default.assert_called_once()

def test_generate_telop_rounded(tmp_path):
    output_dir = tmp_path / "output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    output_file = output_dir / "telop_rounded.png"
    
    result_path = generator.generate_telop(
        text="テストテロップ",
        output_path=str(output_file),
        font_size=24,
        text_color=(255, 255, 255, 255),
        bg_color=(0, 0, 0, 128),
        padding=10,
        border_radius=5
    )
    
    assert result_path == str(output_file)
    assert output_file.exists()
    
    # 画像を開いて検証
    with Image.open(output_file) as img:
        assert img.mode == "RGBA"
        assert img.width > 0
        assert img.height > 0

def test_generate_telop_rect(tmp_path):
    output_dir = tmp_path / "output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    output_file = output_dir / "telop_rect.png"
    
    result_path = generator.generate_telop(
        text="テストテロップ2",
        output_path=str(output_file),
        font_size=20,
        text_color=(255, 0, 0, 255),
        bg_color=(255, 255, 255, 255),
        padding=5,
        border_radius=0
    )
    
    assert result_path == str(output_file)
    assert output_file.exists()

def test_generate_video_theme_telop_all_args(tmp_path):
    output_dir = tmp_path / "output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    output_file = output_dir / "custom_theme.png"
    
    result_path = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme="テーマ解説",
        output_path=str(output_file)
    )
    
    assert result_path == str(output_file)
    assert output_file.exists()

def test_generate_video_theme_telop_no_theme(tmp_path):
    output_dir = tmp_path / "output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    output_file = output_dir / "custom_theme_no.png"
    
    result_path = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme=None,
        output_path=str(output_file)
    )
    
    assert result_path == str(output_file)
    assert output_file.exists()

def test_generate_video_theme_telop_default_path(tmp_path):
    output_dir = tmp_path / "output"
    generator = ThemeTelopGenerator(output_dir=str(output_dir))
    
    result_path = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme="デフォルトパス"
    )
    
    expected_path = output_dir / "theme_telop.png"
    assert result_path == str(expected_path)
    assert expected_path.exists()

def test_main_block():
    Path("backend/temp").mkdir(parents=True, exist_ok=True)
    with mock.patch("builtins.print") as mock_print:
        main()
        mock_print.assert_called()


def test_init_mkdir_failure(monkeypatch):
    from pathlib import Path
    def mock_mkdir(*args, **kwargs):
        raise OSError("Permission denied")
    
    monkeypatch.setattr(Path, "mkdir", mock_mkdir)
    
    with pytest.raises(OSError, match="Permission denied"):
        ThemeTelopGenerator(output_dir="/invalid_permission_dir")


def test_init_env_font(monkeypatch, tmp_path):
    test_font_path = str(tmp_path / "dummy_font.ttf")
    monkeypatch.setenv("THEME_TELOP_FONT_PATH", test_font_path)
    
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    assert generator.font_paths[0] == test_font_path


def test_get_font_invalid_size():
    generator = ThemeTelopGenerator()
    with pytest.raises(ValueError, match="Invalid font size"):
        generator._get_font(size=7)
    with pytest.raises(ValueError, match="Invalid font size"):
        generator._get_font(size=201)


def test_generate_telop_validation_errors(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    # 1. 空のテキスト
    with pytest.raises(ValueError, match="Text cannot be empty."):
        generator.generate_telop("", output_file)
        
    # 2. 長すぎるテキスト
    long_text = "A" * 201
    with pytest.raises(ValueError, match="Text length .* exceeds maximum allowed"):
        generator.generate_telop(long_text, output_file)
        
    # 3. 範囲外のフォントサイズ
    with pytest.raises(ValueError, match="Invalid font_size"):
        generator.generate_telop("Test", output_file, font_size=7)
    with pytest.raises(ValueError, match="Invalid font_size"):
        generator.generate_telop("Test", output_file, font_size=201)
        
    # 4. 範囲外のパディング
    with pytest.raises(ValueError, match="Invalid padding"):
        generator.generate_telop("Test", output_file, padding=-1)
    with pytest.raises(ValueError, match="Invalid padding"):
        generator.generate_telop("Test", output_file, padding=101)
        
    # 5. 範囲外の角丸半径
    with pytest.raises(ValueError, match="Invalid border_radius"):
        generator.generate_telop("Test", output_file, border_radius=-1)
    with pytest.raises(ValueError, match="Invalid border_radius"):
        generator.generate_telop("Test", output_file, border_radius=101)


def test_generate_telop_safety_limits(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    with pytest.raises(ValueError, match="exceed safety limits"):
        generator.generate_telop(
            text="A" * 150,
            output_path=output_file,
            font_size=150,
            padding=100
        )


def test_generate_telop_save_failure(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    with mock.patch("PIL.Image.Image.save", side_effect=OSError("Save failed")):
        with pytest.raises(OSError, match="Could not save generated telop image"):
            generator.generate_telop("Test", str(tmp_path / "telop.png"))


def test_draw_rounded_rectangle_zero_radius():
    generator = ThemeTelopGenerator()
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 直接_draw_rounded_rectangleを呼び出すことで、211-212行の分岐を通す
    generator._draw_rounded_rectangle(
        draw,
        (0, 0, 100, 100),
        corner_radius=0,
        fill=(255, 255, 255, 255)
    )


def test_main_execution(monkeypatch, tmp_path):
    import runpy
    import backend.theme_telop as theme_telop
    original_generate = theme_telop.ThemeTelopGenerator.generate_video_theme_telop
    
    def mock_generate(self, speaker1, speaker2, theme, output_path=None):
        test_out = str(tmp_path / "theme_telop_test.png")
        return original_generate(self, speaker1, speaker2, theme, output_path=test_out)
        
    monkeypatch.setattr(theme_telop.ThemeTelopGenerator, "generate_video_theme_telop", mock_generate)
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
    
    module_path = str(Path(theme_telop.__file__).resolve())
    runpy.run_path(module_path, run_name="__main__")
