import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
from PIL import Image
import importlib

# テスト対象をインポート
# 注: インポート時に `TEMP_DIR.mkdir` が走りますが、テスト環境でも `BASE_DIR` が正しく解釈されれば
# ディレクトリが作成されるだけで問題ありません。
import gen_telops

def test_generate_telops_success(capsys):
    # ImageFont.truetype のモック
    mock_font = MagicMock()
    # PIL の ImageDraw.text が内部で getmask2 を呼んでアンパックするため、ダミーの(mask.im, offset)を返す
    # mask には Image オブジェクトそのものではなく ImagingCore (.im) を渡す必要がある
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    
    # Image.open の戻り値を本物の Image オブジェクト（ただしメモリ上で作成）にする
    # これにより resize や paste も自然に動作する
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    # combined.save を追跡するためのモックターゲット
    # combined は Image.new('RGBA', (430, 45), (0, 0, 0, 0)) で作成されるため、
    # Image.new 自体をラップして、生成されたオブジェクトの `save` メソッドをモックします。
    
    original_new = Image.new
    saved_paths = []

    def mock_new(mode, size, color=0):
        img = original_new(mode, size, color)
        # combined 画像 (サイズが 430, 45) の save をフック
        if size == (430, 45):
            mock_save = MagicMock()
            # saveが呼ばれたら、保存先パスを記録
            def save_side_effect(fp, *args, **kwargs):
                saved_paths.append(fp)
            mock_save.side_effect = save_side_effect
            img.save = mock_save
        return img

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font) as mock_truetype, \
         patch("gen_telops.Image.open", return_value=logo_image) as mock_open, \
         patch("gen_telops.Image.new", side_effect=mock_new):
        
        gen_telops.generate_telops()
        
    # アサーション
    # 1. ImageFont.truetype が 18pt で呼び出されたこと
    mock_truetype.assert_called_once_with(r"C:\Windows\Fonts\msgothic.ttc", 18)
    
    # 2. Image.open が LOGO_PATH で呼び出されたこと
    # ループ内で毎回開かれるので、呼び出し回数は THEMES の長さと同じ
    assert mock_open.call_count == 1
    for call in mock_open.call_args_list:
        assert call[0][0] == gen_telops.LOGO_PATH
        
    # 3. 各画像が正しいファイル名で保存されたこと
    assert len(saved_paths) == len(gen_telops.THEMES)
    for i, path in enumerate(saved_paths):
        assert path == gen_telops.TEMP_DIR / f"brand_telop_{i}.png"
        
    # 4. 標準出力に完了メッセージが出力されたこと
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_missing_logo():
    # ImageFont.truetype のモック
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))

    # ロゴ画像が存在しない場合、Image.open が FileNotFoundError を投げる
    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", side_effect=FileNotFoundError("Logo not found")):
        
        with pytest.raises(FileNotFoundError):
            gen_telops.generate_telops()


def test_generate_telops_missing_font():
    # フォントが存在しない場合、ImageFont.truetype が OSError を投げる
    with patch("gen_telops.ImageFont.truetype", side_effect=OSError("Font not found")):
        
        with pytest.raises(OSError):
            gen_telops.generate_telops()


def test_main_execution(capsys):
    # __name__ == "__main__" ブロックのカバー
    # runpy を使用してモジュールを __main__ として実行する
    import runpy
    
    # 実行時の依存をモックする
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    # combined.save が呼ばれたときに実ファイル書き込みを防ぐため、Image.newをモック
    mock_combined = MagicMock()
    
    # sys.modules から一度削除し、確実に再インポート（再評価）されるようにする
    # テスト実行後に元に戻せるように退避します
    old_gen_telops = sys.modules.get("gen_telops")
    sys.modules.pop("gen_telops", None)
    
    try:
        with patch("gen_telops.ImageFont.truetype", return_value=mock_font) as mock_truetype, \
             patch("gen_telops.Image.open", return_value=logo_image) as mock_open, \
             patch("gen_telops.Image.new", return_value=mock_combined) as mock_new:
            
            runpy.run_module("gen_telops", run_name="__main__")
            
            # generate_telops が実行され、ImageFont.truetype が呼ばれたことをアサート
            mock_truetype.assert_called_once()
            # 各THEMESに対してロゴ画像が開かれたことをアサート
            # call_count is now always 1 as Image.open was optimized to run outside loop
            assert mock_open.call_count == 1
            # Image.new が combined 等のために呼び出されていること
            assert mock_new.call_count > 0
    finally:
        if old_gen_telops is not None:
            sys.modules["gen_telops"] = old_gen_telops
        
    # 標準出力に完了メッセージが出力されたこと
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_rgb_logo(capsys):
    # RGBモードのロゴ画像のテスト
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    # モードをRGBにする
    logo_image = Image.new("RGB", (23, 45), (255, 0, 0))

    original_new = Image.new
    saved_paths = []

    def mock_new(mode, size, color=0):
        img = original_new(mode, size, color)
        if size == (430, 45):
            mock_save = MagicMock()
            def save_side_effect(fp, *args, **kwargs):
                saved_paths.append(fp)
            mock_save.side_effect = save_side_effect
            img.save = mock_save
        return img

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font) as mock_truetype, \
         patch("gen_telops.Image.open", return_value=logo_image) as mock_open, \
         patch("gen_telops.Image.new", side_effect=mock_new):
        
        gen_telops.generate_telops()
        
    assert mock_open.call_count == 1
    assert len(saved_paths) == len(gen_telops.THEMES)
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_empty_themes(capsys):
    # THEMESが空の場合のテスト
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.THEMES", []):
        
        gen_telops.generate_telops()
        
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_save_failure():
    # 画像保存時にOSErrorが発生する場合のテスト
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    original_new = Image.new

    def mock_new(mode, size, color=0):
        img = original_new(mode, size, color)
        if size == (430, 45):
            mock_save = MagicMock(side_effect=OSError("Disk full"))
            img.save = mock_save
        return img

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.Image.new", side_effect=mock_new):
        
        with pytest.raises(OSError, match="Disk full"):
            gen_telops.generate_telops()


def test_import_creates_directory():
    # モジュールインポート時にTEMP_DIRが自動作成されることを検証
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        importlib.reload(gen_telops)
        mock_mkdir.assert_called()


def test_generate_telops_special_themes(capsys):
    # 特殊な文字列（空文字、長文、絵文字、サロゲートペア）がTHEMESに含まれる場合の検証
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))
    
    special_themes = [
        "",
        "A" * 1000,
        "テスト：日本語の混在表現",
        "Emoji: 🍣🎨🖊️",
        "Surrogate: \U0001F600"
    ]
    
    original_new = Image.new
    mock_images = []
    
    def side_effect(mode, size, color=0):
        img = original_new(mode, size, color)
        if size == (430, 45):
            img.save = MagicMock()
            mock_images.append(img)
        return img
        
    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.THEMES", special_themes), \
         patch("gen_telops.Image.new", side_effect=side_effect):
         
        gen_telops.generate_telops()
        
        assert len(mock_images) == len(special_themes)
        for img in mock_images:
            img.save.assert_called_once()
            
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_extreme_logo_sizes(capsys):
    # 極端なサイズのロゴ画像が与えられた場合の検証（極小、極大）
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    
    original_new = Image.new
    
    for size in [(1, 1), (1000, 1000)]:
        logo_image = Image.new("RGBA", size, (255, 0, 0, 255))
        mock_save = MagicMock()
        
        def mock_new(mode, size_new, color=0):
            img = original_new(mode, size_new, color)
            if size_new == (430, 45):
                img.save = mock_save
            return img
            
        with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
             patch("gen_telops.Image.open", return_value=logo_image), \
             patch("gen_telops.THEMES", ["テストテーマ"]), \
             patch("gen_telops.Image.new", side_effect=mock_new):
             
            gen_telops.generate_telops()
            mock_save.assert_called_once()
    
    captured = capsys.readouterr()
    assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_invalid_theme_type(capsys):
    # THEMESに文字列以外(Noneなど)が含まれる場合の検証
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.THEMES", [None]):
        
        # 例外を投げずに正常に完了すること
        gen_telops.generate_telops()
        captured = capsys.readouterr()
        assert "⚠️ インデックス 0 のテーマは文字列ではないためスキップします: None" in captured.out
        assert "✅ テロップ生成完了" in captured.out


def test_generate_telops_corrupted_logo():
    # ロゴ画像が破損しており、UnidentifiedImageErrorが発生する場合の検証
    from PIL import UnidentifiedImageError
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", side_effect=UnidentifiedImageError("Corrupted image")):
        
        with pytest.raises(UnidentifiedImageError):
            gen_telops.generate_telops()


def test_generate_telops_unsupported_save_format():
    # combined.save が ValueError（サポートされていないフォーマットなど）を投げる場合の検証
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))

    original_new = Image.new

    def mock_new(mode, size, color=0):
        img = original_new(mode, size, color)
        if size == (430, 45):
            mock_save = MagicMock(side_effect=ValueError("Unknown format"))
            img.save = mock_save
        return img

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.Image.new", side_effect=mock_new):
        
        with pytest.raises(ValueError, match="Unknown format"):
            gen_telops.generate_telops()



def test_generate_telops_fallback_to_default_font(capsys):
    # フォントがない場合にデフォルトフォントにフォールバックすることを検証
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    
    with patch("gen_telops.FONT_PATH", None), \
         patch("gen_telops.Image.open", return_value=logo_image), \
         patch("gen_telops.ImageFont.load_default", return_value=mock_font) as mock_load_default:
        
        gen_telops.generate_telops()
        mock_load_default.assert_called()
        
    captured = capsys.readouterr()
    assert "⚠️ 指定されたフォントが見つからなかったため、デフォルトフォントを使用します。" in captured.out
    assert "✅ テロップ生成完了" in captured.out


def test_base_dir_env_variable(monkeypatch):
    # 環境変数 VIDEO_AUTOMATION_BASE_DIR が指定されている場合を検証
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", r"C:\fake\base\dir")
    import importlib
    import gen_telops
    importlib.reload(gen_telops)
    assert gen_telops.BASE_DIR == Path(r"C:\fake\base\dir")
    # 元に戻す
    monkeypatch.delenv("VIDEO_AUTOMATION_BASE_DIR", raising=False)
    importlib.reload(gen_telops)


def test_base_dir_fallback(monkeypatch):
    # 環境変数なし、かつデフォルトディレクトリにbackendがない場合のフォールバックを検証
    monkeypatch.delenv("VIDEO_AUTOMATION_BASE_DIR", raising=False)
    
    # Path.exists をモックして、backend ディレクトリが存在しないように見せる
    original_exists = Path.exists
    def mock_exists(self):
        if self.name == "backend":
            return False
        return original_exists(self)
        
    with patch("pathlib.Path.exists", mock_exists):
        import importlib
        import gen_telops
        importlib.reload(gen_telops)
        assert gen_telops.BASE_DIR == Path(r"C:\Users\PC_User\Desktop\script\video-automation")
        
    # 元に戻す
    importlib.reload(gen_telops)


def test_generate_telops_logo_resize_failure():
    # ロゴ画像のリサイズ失敗時のハンドリングを検証
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    logo_image = Image.new("RGBA", (23, 45), (255, 0, 0, 255))
    
    # logo.resize で OSError を発生させる
    logo_image.resize = MagicMock(side_effect=OSError("Resize failed"))

    with patch("gen_telops.ImageFont.truetype", return_value=mock_font), \
         patch("gen_telops.Image.open", return_value=logo_image):
        
        with pytest.raises(OSError, match="Resize failed"):
            gen_telops.generate_telops()


def test_load_font_specific():
    # _load_font 関数の単体テスト
    # 存在しないフォントパスを指定した場合、デフォルトフォントにフォールバックすること
    with patch("gen_telops.ImageFont.truetype", side_effect=OSError("Font not found")), \
         patch("gen_telops.ImageFont.load_default") as mock_load_default:
        
        gen_telops._load_font("invalid_path.ttf")
        mock_load_default.assert_called_once()

    # パスが None の場合
    with patch("gen_telops.ImageFont.load_default") as mock_load_default:
        gen_telops._load_font(None)
        mock_load_default.assert_called_once()


def test_load_logo_specific(tmp_path):
    # _load_logo 関数の単体テスト
    # 1. 存在しないパス
    with pytest.raises(FileNotFoundError):
        gen_telops._load_logo(tmp_path / "non_existent.png")

    # 2. 正常な読み込み
    logo_file = tmp_path / "test_logo.png"
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    img.save(logo_file)
    
    loaded_logo = gen_telops._load_logo(logo_file)
    assert loaded_logo is not None
    assert loaded_logo.size == (10, 10)
    loaded_logo.close()

    # 3. 破損画像 (OSError)
    corrupted_file = tmp_path / "corrupted_logo.png"
    with open(corrupted_file, "w") as f:
        f.write("not an image")
    
    with pytest.raises(OSError):
         gen_telops._load_logo(corrupted_file)


def test_create_telop_image_dimensions():
    # _create_telop_image 関数の単体テスト
    mock_font = MagicMock()
    mock_font.getmask2.return_value = (Image.new("L", (10, 10)).im, (0, 0))
    
    img = gen_telops._create_telop_image("テストテキスト", mock_font)
    assert img.size == (400, 45)
    assert img.mode == "RGBA"


def test_resize_logo_dimensions():
    # _resize_logo 関数の単体テスト
    logo = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    resized = gen_telops._resize_logo(logo, (23, 45))
    assert resized.size == (23, 45)

    # 不正なサイズパラメータに対する ValueError
    with pytest.raises(ValueError):
        gen_telops._resize_logo(logo, (-5, 45))


def test_composite_telop_dimensions():
    # _composite_telop 関数の単体テスト
    logo = Image.new("RGBA", (23, 45), (255, 0, 0, 255))
    telop = Image.new("RGBA", (400, 45), (0, 255, 0, 128))
    
    combined = gen_telops._composite_telop(logo, telop)
    assert combined.size == (430, 45)
    assert combined.mode == "RGBA"


