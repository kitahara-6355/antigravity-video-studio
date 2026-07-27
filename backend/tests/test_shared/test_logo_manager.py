"""
logo_manager.py のユニットテスト
カバレッジ100%を徹底する
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from PIL import Image, UnidentifiedImageError

# backend パスを追加
sys.path.append(str(Path(__file__).parent.parent.parent))

from logo_manager import LogoManager


@pytest.fixture
def temp_logo_dir(tmp_path):
    """テスト用の一時ロゴディレクトリ"""
    return tmp_path / "branding" / "logos"


def test_init(temp_logo_dir):
    """初期化テスト"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    assert manager.logo_dir == temp_logo_dir
    assert temp_logo_dir.exists()
    assert manager.fallback_logo == temp_logo_dir / "fallback_logo.png"


def test_get_logo_path_exists(temp_logo_dir):
    """ロゴが存在する場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    path = manager.get_logo_path("brand_logo.png")
    assert path == logo_file


def test_get_logo_path_fallback(temp_logo_dir):
    """ロゴが存在せず、フォールバックが存在する場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    manager.fallback_logo.touch()
    
    path = manager.get_logo_path("brand_logo.png")
    assert path == manager.fallback_logo


def test_get_logo_path_none(temp_logo_dir):
    """いずれも存在しない場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    
    path = manager.get_logo_path("brand_logo.png")
    assert path is None


def test_validate_logo_not_exists(temp_logo_dir):
    """ロゴファイルが存在しない場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    assert not manager.validate_logo(temp_logo_dir / "non_existent.png")


def test_validate_logo_unsupported_format(temp_logo_dir):
    """サポートされていない画像フォーマットの場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.gif"
    logo_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "GIF"
    
    with patch("PIL.Image.open", return_value=mock_img):
        assert not manager.validate_logo(logo_file)


def test_validate_logo_too_small(temp_logo_dir):
    """画像が小さすぎる場合"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "PNG"
    mock_img.width = 40
    mock_img.height = 100
    
    with patch("PIL.Image.open", return_value=mock_img):
        assert not manager.validate_logo(logo_file)


def test_validate_logo_very_large(temp_logo_dir):
    """画像が大きすぎる場合（警告ログが出るがTrueを返す）"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "PNG"
    mock_img.width = 2500
    mock_img.height = 100
    
    with patch("PIL.Image.open", return_value=mock_img):
        assert manager.validate_logo(logo_file)


def test_validate_logo_success(temp_logo_dir):
    """バリデーション成功"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "PNG"
    mock_img.width = 500
    mock_img.height = 500
    
    with patch("PIL.Image.open", return_value=mock_img):
        assert manager.validate_logo(logo_file)


def test_validate_logo_exceptions(temp_logo_dir):
    """バリデーション時の例外発生テスト"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    # 1. UnidentifiedImageError の場合
    with patch("PIL.Image.open", side_effect=UnidentifiedImageError("Mocked error")):
        assert not manager.validate_logo(logo_file)
        
    # 2. OSError の場合
    with patch("PIL.Image.open", side_effect=OSError("Mocked error")):
        assert not manager.validate_logo(logo_file)
        
    # 3. ValueError の場合
    with patch("PIL.Image.open", side_effect=ValueError("Mocked error")):
        assert not manager.validate_logo(logo_file)
        
    # 4. AttributeError の場合
    with patch("PIL.Image.open", side_effect=AttributeError("Unexpected Mocked error")):
        assert not manager.validate_logo(logo_file)

    # 5. TypeError の場合
    with patch("PIL.Image.open", side_effect=TypeError("Unexpected Mocked error")):
        assert not manager.validate_logo(logo_file)


def test_get_logo_size_success(temp_logo_dir):
    """ロゴサイズ取得成功"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.width = 120
    mock_img.height = 60
    
    with patch("PIL.Image.open", return_value=mock_img):
        assert manager.get_logo_size(logo_file) == (120, 60)


def test_get_logo_size_exceptions(temp_logo_dir):
    """ロゴサイズ取得時の例外発生テスト"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    logo_file = temp_logo_dir / "brand_logo.png"
    logo_file.touch()
    
    # 1. UnidentifiedImageError
    with patch("PIL.Image.open", side_effect=UnidentifiedImageError("Mocked error")):
        assert manager.get_logo_size(logo_file) == (0, 0)
        
    # 2. OSError
    with patch("PIL.Image.open", side_effect=OSError("Mocked error")):
        assert manager.get_logo_size(logo_file) == (0, 0)
        
    # 3. ValueError
    with patch("PIL.Image.open", side_effect=ValueError("Mocked error")):
        assert manager.get_logo_size(logo_file) == (0, 0)
        
    # 4. AttributeError
    with patch("PIL.Image.open", side_effect=AttributeError("Unexpected Mocked error")):
        assert manager.get_logo_size(logo_file) == (0, 0)

    # 5. TypeError
    with patch("PIL.Image.open", side_effect=TypeError("Unexpected Mocked error")):
        assert manager.get_logo_size(logo_file) == (0, 0)


def test_calculate_target_size():
    """リサイズターゲットサイズ計算テスト"""
    manager = LogoManager()
    
    # 正常系 (200x100 -> 高さを 50 にリサイズ)
    assert manager.calculate_target_size((200, 100), 50) == (100, 50)
    
    # 高さが 0 の場合（ゼロディビジョン回避）
    assert manager.calculate_target_size((200, 0), 50) == (0, 0)


def test_save_uploaded_logo_convert_rgba(temp_logo_dir):
    """アップロードされたロゴの保存テスト（RGB -> RGBA 変換）"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    src_file = temp_logo_dir / "uploaded.png"
    src_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.mode = 'RGB'
    
    mock_rgba_img = MagicMock()
    mock_img.convert.return_value = mock_rgba_img
    
    with patch("PIL.Image.open", return_value=mock_img):
        dest_path = manager.save_uploaded_logo(str(src_file), "saved_logo.png")
        assert dest_path == temp_logo_dir / "saved_logo.png"
        mock_img.convert.assert_called_once_with('RGBA')
        mock_rgba_img.save.assert_called_once()


def test_save_uploaded_logo_no_convert(temp_logo_dir):
    """アップロードされたロゴの保存テスト（すでに RGBA なので変換しない）"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    src_file = temp_logo_dir / "uploaded.png"
    src_file.touch()
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.mode = 'RGBA'
    
    with patch("PIL.Image.open", return_value=mock_img):
        dest_path = manager.save_uploaded_logo(str(src_file), "saved_logo.png")
        assert dest_path == temp_logo_dir / "saved_logo.png"
        mock_img.convert.assert_not_called()
        mock_img.save.assert_called_once()


def test_save_uploaded_logo_exceptions(temp_logo_dir):
    """アップロードロゴ保存時の例外発生テスト"""
    manager = LogoManager(logo_dir=str(temp_logo_dir))
    src_file = temp_logo_dir / "uploaded.png"
    src_file.touch()
    
    # 1. OSError
    with patch("PIL.Image.open", side_effect=OSError("Mocked save error")):
        with pytest.raises(OSError):
            manager.save_uploaded_logo(str(src_file))
            
    # 2. ValueError
    with patch("PIL.Image.open", side_effect=ValueError("Mocked save error")):
        with pytest.raises(ValueError):
            manager.save_uploaded_logo(str(src_file))
            
    # 3. AttributeError
    with patch("PIL.Image.open", side_effect=AttributeError("Unexpected Mocked save error")):
        with pytest.raises(AttributeError) as exc_info:
            manager.save_uploaded_logo(str(src_file))
        assert "Unexpected Mocked save error" in str(exc_info.value)

    # 4. TypeError
    with patch("PIL.Image.open", side_effect=TypeError("Unexpected Mocked save error")):
        with pytest.raises(TypeError) as exc_info:
            manager.save_uploaded_logo(str(src_file))
        assert "Unexpected Mocked save error" in str(exc_info.value)

    # 5. KeyError
    with patch("PIL.Image.open", side_effect=KeyError("Unexpected Mocked save error")):
        with pytest.raises(KeyError) as exc_info:
            manager.save_uploaded_logo(str(src_file))
        assert "Unexpected Mocked save error" in str(exc_info.value)


def test_main_block_no_logo():
    """__main__ブロックの実行テスト（ロゴなし）"""
    import runpy
    with patch("logo_manager.LogoManager.get_logo_path", return_value=None):
        with patch("logging.basicConfig") as mock_logging:
            runpy.run_module("logo_manager", run_name="__main__")
            mock_logging.assert_called_once()


def test_main_block_with_logo():
    """__main__ブロックの実行テスト（ロゴあり）"""
    import runpy
    
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "PNG"
    mock_img.width = 100
    mock_img.height = 100

    with patch("PIL.Image.open", return_value=mock_img), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("logging.basicConfig"), \
         patch("builtins.print") as mock_print:
         
        runpy.run_module("logo_manager", run_name="__main__")
        mock_print.assert_any_call("Original: (100, 100)")
        mock_print.assert_any_call("Target: (60, 60)")





def test_main_block_with_invalid_logo():
    """__main__ブロックの実行テスト（ロゴがあるがバリデーション失敗）"""
    import runpy

    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.format = "GIF"  # サポート外形式でバリデーション失敗をシミュレート

    with patch("PIL.Image.open", return_value=mock_img), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("logging.basicConfig"), \
         patch("builtins.print") as mock_print:
         
        runpy.run_module("logo_manager", run_name="__main__")
        mock_print.assert_not_called()


def test_init_default_fallback_to_branding_logos(tmp_path, monkeypatch):
    """デフォルトパス指定時、branding/logosへのフォールバックテスト"""
    # カレントディレクトリをtmp_pathに変更
    monkeypatch.chdir(tmp_path)
    
    # branding/logos ディレクトリとロゴファイルを作成
    alt_dir = tmp_path / "branding" / "logos"
    alt_dir.mkdir(parents=True)
    (alt_dir / "brand_logo.png").touch()
    
    # backend/branding/logos は存在しない状態にする（デフォルトでは存在しない）
    manager = LogoManager()
    
    # alt_path ("branding/logos") が path に設定されるはず
    assert manager.logo_dir == Path("branding/logos")

