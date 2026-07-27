import pytest
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image, UnidentifiedImageError
from logo_manager import LogoManager

def test_init_creates_dir(tmp_path):
    logo_dir = tmp_path / "logos"
    assert not logo_dir.exists()
    manager = LogoManager(logo_dir=str(logo_dir))
    assert logo_dir.exists()
    assert manager.fallback_logo == logo_dir / "fallback_logo.png"

def test_get_logo_path(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    
    # 正常系（ロゴが存在する）
    logo_file = logo_dir / "brand_logo.png"
    logo_file.touch()
    path = manager.get_logo_path("brand_logo.png")
    assert path == logo_file
    
    # フォールバック（指定ロゴが存在せず、フォールバックが存在する）
    logo_file.unlink()
    fallback_file = logo_dir / "fallback_logo.png"
    fallback_file.touch()
    path = manager.get_logo_path("brand_logo.png")
    assert path == fallback_file
    
    # どちらも存在しない
    fallback_file.unlink()
    path = manager.get_logo_path("brand_logo.png")
    assert path is None

def test_validate_logo_not_exists(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    non_existent = logo_dir / "non_existent.png"
    assert manager.validate_logo(non_existent) is False

def test_validate_logo_success(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    
    # 50x50のPNG画像を作成
    img = Image.new("RGBA", (100, 100), color="red")
    img.save(logo_file, format="PNG")
    
    assert manager.validate_logo(logo_file) is True

def test_validate_logo_unsupported_format(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.gif"
    
    # GIF画像を作成
    img = Image.new("RGBA", (100, 100), color="red")
    img.save(logo_file, format="GIF")
    
    assert manager.validate_logo(logo_file) is False

def test_validate_logo_too_small(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    
    # 40x40の画像（小さすぎる）
    img = Image.new("RGBA", (40, 40), color="red")
    img.save(logo_file, format="PNG")
    
    assert manager.validate_logo(logo_file) is False

def test_validate_logo_very_large(tmp_path, caplog):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    
    # 2001x2001の画像（大きすぎるが警告が出てTrueを返すはず）
    img = Image.new("RGBA", (2001, 2001), color="red")
    img.save(logo_file, format="PNG")
    
    with caplog.at_level(logging.WARNING):
        assert manager.validate_logo(logo_file) is True
        assert "Logo very large" in caplog.text

def test_validate_logo_expected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    logo_file.touch()
    
    # PIL.Image.openが例外を投げる状況をシミュレート
    with patch("PIL.Image.open", side_effect=UnidentifiedImageError("test identification error")):
        assert manager.validate_logo(logo_file) is False
        
    with patch("PIL.Image.open", side_effect=OSError("test os error")):
        assert manager.validate_logo(logo_file) is False
        
    with patch("PIL.Image.open", side_effect=ValueError("test value error")):
        assert manager.validate_logo(logo_file) is False

def test_validate_logo_unexpected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    logo_file.touch()
    
    # 予期せぬ例外をシミュレート
    with patch("PIL.Image.open", side_effect=RuntimeError("unexpected runtime error")):
        assert manager.validate_logo(logo_file) is False

def test_get_logo_size_success(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    img = Image.new("RGBA", (120, 80), color="blue")
    img.save(logo_file, format="PNG")
    
    assert manager.get_logo_size(logo_file) == (120, 80)

def test_get_logo_size_expected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    logo_file.touch()
    
    with patch("PIL.Image.open", side_effect=OSError("test os error")):
        assert manager.get_logo_size(logo_file) == (0, 0)

def test_get_logo_size_unexpected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    logo_file = logo_dir / "test_logo.png"
    logo_file.touch()
    
    with patch("PIL.Image.open", side_effect=RuntimeError("unexpected runtime error")):
        assert manager.get_logo_size(logo_file) == (0, 0)

def test_calculate_target_size():
    manager = LogoManager()
    
    # 正常系
    assert manager.calculate_target_size((200, 100), target_height=60) == (120, 60)
    
    # 高さが0の場合（分母ゼロ回避）
    assert manager.calculate_target_size((200, 0), target_height=60) == (0, 0)

def test_save_uploaded_logo_rgba(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    
    # RGBの元画像を作成
    src_file = tmp_path / "uploaded.jpg"
    img = Image.new("RGB", (100, 100), color="green")
    img.save(src_file, format="JPEG")
    
    dest_path = manager.save_uploaded_logo(str(src_file), "saved_logo.png")
    
    assert dest_path.exists()
    assert dest_path.parent == logo_dir
    assert dest_path.name == "saved_logo.png"
    
    # 保存された画像がRGBAに変換され、PNG形式であることを検証
    with Image.open(dest_path) as saved_img:
        assert saved_img.mode == "RGBA"
        assert saved_img.format == "PNG"

def test_save_uploaded_logo_expected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    src_file = tmp_path / "uploaded.jpg"
    src_file.touch()
    
    # 保存時にOSErrorをシミュレート
    with patch("PIL.Image.open", side_effect=OSError("test os error")):
        with pytest.raises(OSError):
            manager.save_uploaded_logo(str(src_file), "failed_logo.png")

def test_save_uploaded_logo_unexpected_exception(tmp_path):
    logo_dir = tmp_path / "logos"
    manager = LogoManager(logo_dir=str(logo_dir))
    src_file = tmp_path / "uploaded.jpg"
    src_file.touch()
    
    # 保存時に予期せぬ例外をシミュレート
    with patch("PIL.Image.open", side_effect=RuntimeError("unexpected error")):
        with pytest.raises(RuntimeError):
            manager.save_uploaded_logo(str(src_file), "failed_logo.png")
