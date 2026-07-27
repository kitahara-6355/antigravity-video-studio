import os
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import MagicMock, patch

from minimal_telop_generator import MinimalTelopGenerator, generate_all_theme_telops

def test_minimal_telop_generator_init(tmp_path):
    output_dir = tmp_path / "test_telops"
    generator = MinimalTelopGenerator(output_dir=str(output_dir))
    assert generator.output_dir == output_dir
    assert output_dir.exists()

def test_get_font_fallback(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    generator.font_paths = ["/invalid_font_path.ttf"]
    font = generator._get_font(12)
    assert font is not None

def test_generate_minimal_telop_success(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = tmp_path / "telop.png"
    res = generator.generate_minimal_telop(
        theme_text="テストテキスト",
        output_path=str(output_file),
        font_size=16,
        padding=8
    )
    assert res == str(output_file)
    assert output_file.exists()
    with Image.open(output_file) as img:
        assert img.format == "PNG"
        assert img.width > 0
        assert img.height > 0

def test_generate_minimal_telop_validation(tmp_path):
    generator = MinimalTelopGenerator(output_dir=str(tmp_path))
    output_file = str(tmp_path / "telop.png")
    
    # 1. 空のテキスト
    with pytest.raises(ValueError, match="theme_text cannot be empty."):
        generator.generate_minimal_telop("", output_file)
        
    # 2. 不適切なフォントサイズ (<=0)
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=0)
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=-10)
        
    # 3. 不適切なフォントサイズ (>200)
    with pytest.raises(ValueError, match="Invalid font_size."):
        generator.generate_minimal_telop("Test", output_file, font_size=201)
        
    # 4. 不適切なパディング (<0)
    with pytest.raises(ValueError, match="Invalid padding."):
        generator.generate_minimal_telop("Test", output_file, padding=-1)
        
    # 5. 不適切なパディング (>100)
    with pytest.raises(ValueError, match="Invalid padding."):
        generator.generate_minimal_telop("Test", output_file, padding=101)

def test_generate_all_theme_telops(tmp_path, monkeypatch):
    test_output_dir = tmp_path / "all_telops"
    original_init = MinimalTelopGenerator.__init__
    def mock_init(self, output_dir=None):
        original_init(self, output_dir=str(test_output_dir))
    monkeypatch.setattr(MinimalTelopGenerator, "__init__", mock_init)
    generated = generate_all_theme_telops()
    assert len(generated) > 0
    for theme, path in generated.items():
        assert Path(path).exists()
        assert Path(path).parent == test_output_dir
