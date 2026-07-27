"""
Theme Telop Generator Tests
"""

import os
import pytest
from pathlib import Path
from theme_telop import ThemeTelopGenerator
from PIL import Image


def test_font_fallback_and_env(monkeypatch, tmp_path):
    # テスト用の一時フォントパス環境変数
    test_font_path = str(tmp_path / "dummy_font.ttf")
    monkeypatch.setenv("THEME_TELOP_FONT_PATH", test_font_path)
    
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    
    # 環境変数で指定したフォントが font_paths の先頭に入っていること
    assert generator.font_paths[0] == test_font_path
    
    # 存在しないフォントなのでフォールバックしてデフォルトフォントをロードできること
    font = generator._get_font(24)
    assert font is not None


def test_resource_limits_validation(tmp_path):
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


def test_successful_generation(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    res_path = generator.generate_telop(
        text="北原美麗 × 山田タロウ：想いを筆で起こす",
        output_path=output_file,
        font_size=24,
        padding=10,
        border_radius=5
    )
    
    assert res_path == output_file
    assert os.path.exists(output_file)
    
    # 生成された画像がPNGであり、サイズが適切であることを確認
    with Image.open(output_file) as img:
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0


def test_file_io_error_handling(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    
    # 存在しない、または書き込み権限がないはずの無効なパス
    invalid_path = "/invalid_path_dir_does_not_exist/telop.png"
    if os.name == 'nt':
        invalid_path = "Z:\\invalid_drive_does_not_exist\\telop.png"
        
    with pytest.raises((OSError, ValueError)):
        generator.generate_telop("Test", invalid_path)


def test_draw_rounded_rectangle_edge_cases(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    # 角丸半径が画像サイズに対して極端に大きい場合でも、自動クリップされて正常終了すること
    res_path = generator.generate_telop(
        text="Short",
        output_path=output_file,
        font_size=12,
        padding=5,
        border_radius=50  # 画像全体のサイズより大きい
    )
    assert os.path.exists(res_path)


def test_output_dir_creation_failure(monkeypatch):
    def mock_mkdir(*args, **kwargs):
        raise OSError("Permission denied")
    
    monkeypatch.setattr(Path, "mkdir", mock_mkdir)
    
    with pytest.raises(OSError, match="Permission denied"):
        ThemeTelopGenerator(output_dir="/invalid_permission_dir")


def test_get_font_invalid_size(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="Invalid font size"):
        generator._get_font(7)
    with pytest.raises(ValueError, match="Invalid font size"):
        generator._get_font(201)


def test_font_load_exception_fallback(monkeypatch, tmp_path):
    from PIL import ImageFont
    original_truetype = ImageFont.truetype
    
    # 読み込もうとしているフォントがファイルパス（文字列またはPathオブジェクト）の場合は例外
    def mock_truetype(font, *args, **kwargs):
        if isinstance(font, (str, Path)):
            raise RuntimeError("Mocked font load error")
        return original_truetype(font, *args, **kwargs)
    
    monkeypatch.setattr(ImageFont, "truetype", mock_truetype)
    
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    # _get_font(24) がデフォルトフォントを返す（例外が出ないこと）
    font = generator._get_font(24)
    assert font is not None


def test_safety_limits_exceeded(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    # 非常に大きなフォントサイズと長いテキストで安全制限を超える
    with pytest.raises(ValueError, match="exceed safety limits"):
        generator.generate_telop(
            text="A" * 150,
            output_path=output_file,
            font_size=150,
            padding=100
        )


def test_zero_border_radius(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    # 1. border_radius = 0 のテスト（通常のdraw.rectangleを通る）
    res_path = generator.generate_telop(
        text="Test Zero Radius",
        output_path=output_file,
        border_radius=0
    )
    assert os.path.exists(res_path)
    
    # 2. _draw_rounded_rectangle の corner_radius=0 分岐の直接テスト
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    generator._draw_rounded_rectangle(
        draw,
        (0, 0, 100, 100),
        corner_radius=0,
        fill=(255, 255, 255, 255)
    )


def test_generate_video_theme_telop(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    
    # 1. テーマありのテスト
    out_path_1 = str(tmp_path / "theme_1.png")
    res_1 = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme="テストテーマ",
        output_path=out_path_1
    )
    assert res_1 == out_path_1
    assert os.path.exists(out_path_1)
    
    # 2. テーマなし、かつ output_path が None のテスト
    res_2 = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme="",
        output_path=None
    )
    # output_dir / "theme_telop.png" に保存されるはず
    expected_path = str(Path(tmp_path) / "theme_telop.png")
    assert res_2 == expected_path
    assert os.path.exists(expected_path)


def test_main_execution(monkeypatch, tmp_path):
    import runpy
    import theme_telop
    original_generate = theme_telop.ThemeTelopGenerator.generate_video_theme_telop
    
    def mock_generate(self, speaker1, speaker2, theme, output_path=None):
        test_out = str(tmp_path / "theme_telop_test.png")
        return original_generate(self, speaker1, speaker2, theme, output_path=test_out)
        
    monkeypatch.setattr(theme_telop.ThemeTelopGenerator, "generate_video_theme_telop", mock_generate)
    
    # stdout の print をキャプチャするために monkeypatch
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)
    
    # runpyを使って __main__ として実行
    module_path = str(Path(theme_telop.__file__).resolve())
    runpy.run_path(module_path, run_name="__main__")


def test_generate_video_theme_telop_none_theme(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    
    # themeにNoneが渡された場合の挙動をテスト
    out_path = str(tmp_path / "theme_none.png")
    res = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2="話者B",
        theme=None,
        output_path=out_path
    )
    assert res == out_path
    assert os.path.exists(out_path)
    
    # 画像ファイルが生成され、適切なフォーマットか確認
    with Image.open(out_path) as img:
        assert img.format == "PNG"


def test_extreme_speaker_names(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_extreme.png")
    
    # 話者名が長すぎて合計で200文字を超える場合
    long_speaker1 = "A" * 105
    long_speaker2 = "B" * 105
    
    with pytest.raises(ValueError, match="Text length .* exceeds maximum allowed"):
        generator.generate_video_theme_telop(
            speaker1=long_speaker1,
            speaker2=long_speaker2,
            theme="テストテーマ",
            output_path=output_file
        )


def test_color_alpha_variations(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_colors.png")
    
    # 完全に不透明、完全に透明、半透明など
    res = generator.generate_telop(
        text="Color Test",
        output_path=output_file,
        text_color=(255, 0, 0, 128),  # 半透明赤
        bg_color=(0, 255, 0, 0),      # 完全に透明緑
    )
    assert os.path.exists(res)


def test_output_path_as_path_object(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = tmp_path / "telop_path_obj.png"  # Pathオブジェクト
    
    res = generator.generate_telop(
        text="Path Obj Test",
        output_path=output_file
    )
    # 戻り値は文字列だが、指し示すパスは一致するはず
    assert Path(res) == output_file
    assert output_file.exists()


def test_validation_boundary_values(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_boundary.png")
    
    # text: 長さ 1 (境界最小)
    res1 = generator.generate_telop("A", output_file, font_size=24, padding=10, border_radius=5)
    assert os.path.exists(res1)
    
    # text: 長さ 200 (境界最大)
    res2 = generator.generate_telop("A" * 200, output_file, font_size=24, padding=10, border_radius=5)
    assert os.path.exists(res2)
    
    # font_size: 8 (境界最小)
    res3 = generator.generate_telop("Test", output_file, font_size=8, padding=10, border_radius=5)
    assert os.path.exists(res3)
    
    # font_size: 200 (境界最大)
    # ※フォントサイズ200で長い文字列だと安全制限(3840x2160)を超えるため、短い文字列にする
    res4 = generator.generate_telop("T", output_file, font_size=200, padding=10, border_radius=5)
    assert os.path.exists(res4)
    
    # padding: 0 (境界最小)
    res5 = generator.generate_telop("Test", output_file, font_size=24, padding=0, border_radius=5)
    assert os.path.exists(res5)
    
    # padding: 100 (境界最大)
    # ※パディング100で長い文字列だと安全制限を超えるため、短い文字列にする
    res6 = generator.generate_telop("T", output_file, font_size=24, padding=100, border_radius=5)
    assert os.path.exists(res6)
    
    # border_radius: 0 (境界最小)
    res7 = generator.generate_telop("Test", output_file, font_size=24, padding=10, border_radius=0)
    assert os.path.exists(res7)
    
    # border_radius: 100 (境界最大)
    res8 = generator.generate_telop("Test", output_file, font_size=24, padding=10, border_radius=100)
    assert os.path.exists(res8)


def test_validation_invalid_types(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_type_error.png")
    
    # text が None (ValueError が発生することを確認)
    with pytest.raises(ValueError, match="Text cannot be empty."):
        generator.generate_telop(None, output_file)
        
    # text が不正型 (int)
    with pytest.raises(TypeError):
        generator.generate_telop(123, output_file)  # len(123) や textbbox でエラーになるはず
        
    # font_size が None
    with pytest.raises(TypeError):
        generator.generate_telop("Test", output_file, font_size=None)
        
    # padding が None
    with pytest.raises(TypeError):
        generator.generate_telop("Test", output_file, padding=None)
        
    # border_radius が None
    with pytest.raises(TypeError):
        generator.generate_telop("Test", output_file, border_radius=None)


def test_safety_limits_exact_boundaries(tmp_path, monkeypatch):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_safety.png")
    
    # _measure_text_size をモックして、ちょうど境界値になるようにする
    # max_width = 3840, max_height = 2160
    # padding = 10 のとき、img_width = text_width + 20, img_height = text_height + 20
    # つまり text_width = 3820, text_height = 2140 のとき img_width = 3840, img_height = 2160
    
    # ちょうどセーフな場合 (3840 x 2160)
    monkeypatch.setattr(generator, "_measure_text_size", lambda text, font: (3820, 2140))
    res = generator.generate_telop("BoundarySafe", output_file, padding=10)
    assert os.path.exists(res)
    
    # 幅が 1px 超えてアウトな場合 (3841 x 2160)
    monkeypatch.setattr(generator, "_measure_text_size", lambda text, font: (3821, 2140))
    with pytest.raises(ValueError, match="exceed safety limits"):
        generator.generate_telop("BoundaryWidthOut", output_file, padding=10)
        
    # 高さが 1px 超えてアウトな場合 (3840 x 2161)
    monkeypatch.setattr(generator, "_measure_text_size", lambda text, font: (3820, 2141))
    with pytest.raises(ValueError, match="exceed safety limits"):
        generator.generate_telop("BoundaryHeightOut", output_file, padding=10)


def test_draw_rounded_rectangle_negative_radius(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # corner_radius が負の値の場合、内部で 0 にクリップされて正常終了すること
    generator._draw_rounded_rectangle(
        draw,
        (0, 0, 100, 100),
        corner_radius=-10,
        fill=(255, 255, 255, 255)
    )
    
    # また、x0 > x1 や y0 > y1 などの不正座標が与えられた場合、
    # 内部の draw.rectangle 呼び出しで ValueError がスローされることを確認
    with pytest.raises(ValueError, match="x1 must be greater than or equal to x0"):
        generator._draw_rounded_rectangle(
            draw,
            (100, 100, 0, 0),  # 逆転座標
            corner_radius=5,
            fill=(255, 255, 255, 255)
        )



def test_generate_video_theme_telop_none_speaker(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "theme_speaker_none.png")
    
    # speaker1 または speaker2 に None が渡された場合
    # (Pythonのf-stringにより "None" という文字列として結合されるため、TypeErrorにならず処理される挙動を確認)
    res1 = generator.generate_video_theme_telop(
        speaker1=None,
        speaker2="話者B",
        theme="テーマ",
        output_path=output_file
    )
    assert os.path.exists(res1)
    
    res2 = generator.generate_video_theme_telop(
        speaker1="話者A",
        speaker2=None,
        theme="テーマ",
        output_path=output_file
    )
    assert os.path.exists(res2)


def test_special_characters_text(tmp_path):
    generator = ThemeTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop_special.png")
    
    # 絵文字、改行、タブを含むテキストの生成確認
    special_text = "✨絵文字テスト✨\n改行と\tタブ"
    res = generator.generate_telop(
        text=special_text,
        output_path=output_file,
        font_size=16
    )
    assert os.path.exists(res)
    with Image.open(res) as img:
        assert img.width > 0
        assert img.height > 0


