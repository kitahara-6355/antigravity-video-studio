# -*- coding: utf-8 -*-
import sys
import os
import pytest
from pathlib import Path
from PIL import Image
import io

# プロジェクトルートとbackendをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.services.thumbnail_analyzer import thumbnail_analyzer

def create_dummy_image_file(path: Path, width: int, height: int, format: str = "PNG", target_size_bytes: int = 0):
    """テスト用のダミー画像ファイルを生成"""
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format=format)
    data = img_byte_arr.getvalue()
    if len(data) < target_size_bytes:
        data += b'\x00' * (target_size_bytes - len(data))
    path.write_bytes(data)

def test_generate_thumbnail_valid(tmp_path):
    """正常系: 正常なパラメータでサムネイルが生成され、検証を通ることをテスト"""
    out_path = tmp_path / "valid_thumb.png"
    text = "Antigravity Quality Test"
    
    res_path = thumbnail_analyzer.generate_thumbnail(
        out_path, width=1280, height=720, text=text, draw_arrow=True, draw_circle=True, use_banner=True
    )
    
    assert res_path == out_path
    assert out_path.exists()
    
    # 検証を実行
    res = thumbnail_analyzer.validate_thumbnail(out_path)
    assert res["width"] == 1280
    assert res["height"] == 720
    assert res["size_bytes"] > 0
    assert res["size_bytes"] < 4 * 1024 * 1024
    
    # 画像が破損しておらず、Pillowで正常ロード可能か検証
    with Image.open(out_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_validate_thumbnail_file_not_found():
    """異常系: ファイルが存在しない場合に FileNotFoundError を投げることをテスト"""
    with pytest.raises(FileNotFoundError) as exc_info:
        thumbnail_analyzer.validate_thumbnail("non_existent_file_path.png")
    assert "Thumbnail file not found" in str(exc_info.value)

def test_validate_thumbnail_empty_path():
    """異常系: パスが空またはNoneの場合に ValueError を投げることをテスト"""
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail("")
    assert "File path must not be empty or None" in str(exc_info.value)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(None)
    assert "File path must not be empty or None" in str(exc_info.value)

def test_validate_thumbnail_invalid_format(tmp_path):
    """異常系: サポートされていない画像フォーマットの検証で ValueError を投げることをテスト"""
    out_path = tmp_path / "invalid_format.gif"
    create_dummy_image_file(out_path, 1280, 720, format="GIF")
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Unsupported file format" in str(exc_info.value)

def test_validate_thumbnail_empty_file(tmp_path):
    """異常系: 0バイトのファイルを検証した際に ValueError を投げることをテスト"""
    out_path = tmp_path / "empty_file.png"
    out_path.write_bytes(b"")
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Thumbnail file is empty" in str(exc_info.value)

def test_validate_thumbnail_exceeds_4mb(tmp_path):
    """異常系: ファイルサイズが4MB以上の場合に ValueError を投げることをテスト"""
    out_path = tmp_path / "too_large.png"
    # 4.1MBのダミーファイルを書き込み
    create_dummy_image_file(out_path, 1280, 720, target_size_bytes=int(4.1 * 1024 * 1024))
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "File size exceeds 4MB limit" in str(exc_info.value)

def test_validate_thumbnail_corrupted_header(tmp_path):
    """異常系: 拡張子は.pngだがPNGヘッダーを持たない場合に ValueError を投げることをテスト"""
    out_path = tmp_path / "corrupted_header.png"
    out_path.write_bytes(b"GAGGADADADASDA" + b"\x00" * 100)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Image is corrupted or invalid format" in str(exc_info.value)

def test_validate_thumbnail_corrupted_pixel(tmp_path):
    """異常系: 画像のピクセルデータが破損している場合に ValueError を投げることをテスト"""
    out_path = tmp_path / "corrupted_pixel.png"
    # PNGヘッダーだけ書き込み、中身は破損データ
    out_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Image is corrupted or invalid format" in str(exc_info.value) or "Failed to load image pixels" in str(exc_info.value)

def test_validate_thumbnail_insufficient_resolution(tmp_path):
    """異常系: 解像度が1280x720未満の場合に ValueError を投げることをテスト"""
    out_path = tmp_path / "low_res.png"
    create_dummy_image_file(out_path, 1279, 720)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Resolution must be at least 1280x720" in str(exc_info.value)

def test_validate_thumbnail_exceeds_max_resolution(tmp_path):
    """異常系: 解像度が8Kを超える場合に ValueError を投げることをテスト"""
    out_path = tmp_path / "too_large_res.png"
    # 7681x4320 は 8Kを超える
    create_dummy_image_file(out_path, 7681, 4320)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Resolution exceeds maximum limit of 8K" in str(exc_info.value)

def test_validate_thumbnail_invalid_aspect_ratio(tmp_path):
    """異常系: アスペクト比が16:9でない画像（誤差0.01超）で ValueError を投げることをテスト"""
    out_path = tmp_path / "bad_aspect.png"
    # 1280x960 (4:3)
    create_dummy_image_file(out_path, 1280, 960)
    
    with pytest.raises(ValueError) as exc_info:
        thumbnail_analyzer.validate_thumbnail(out_path)
    assert "Aspect ratio must be 16:9" in str(exc_info.value)

def test_generate_thumbnail_invalid_resolutions(tmp_path):
    """異常系: 生成時に無効な解像度を渡した際、適切な ValueError を投げることをテスト"""
    out_path = tmp_path / "test.png"
    
    # 負の解像度
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        thumbnail_analyzer.generate_thumbnail(out_path, width=-1280, height=720)
        
    # ゼロ解像度
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        thumbnail_analyzer.generate_thumbnail(out_path, width=1280, height=0)
        
    # 数値変換できない文字列
    with pytest.raises(ValueError, match="Width and height must be integers"):
        thumbnail_analyzer.generate_thumbnail(out_path, width="not_an_int", height=720)

def test_generate_thumbnail_exceeds_max_limit(tmp_path):
    """異常系: 生成時に8Kを超える解像度を渡した際、ValueError を投げることをテスト"""
    out_path = tmp_path / "test.png"
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit of 8K"):
        thumbnail_analyzer.generate_thumbnail(out_path, width=7681, height=4320)

def test_generate_thumbnail_long_text_and_empty_text(tmp_path):
    """検証: テキストが空、None、または極端に長い場合の堅牢性テスト"""
    out_path_empty = tmp_path / "empty_text.png"
    thumbnail_analyzer.generate_thumbnail(out_path_empty, text="")
    assert thumbnail_analyzer.validate_thumbnail(out_path_empty)["width"] == 1280
    
    out_path_none = tmp_path / "none_text.png"
    thumbnail_analyzer.generate_thumbnail(out_path_none, text=None)
    assert thumbnail_analyzer.validate_thumbnail(out_path_none)["width"] == 1280
    
    out_path_long = tmp_path / "long_text.png"
    long_text = "これは非常に長いテキストのテストケースです。このテキストは複数行に折り返される必要があります。バナー内にはみ出さず、画像が破損することなく、最後までクラッシュせずに生成されることをテストします。" * 10
    thumbnail_analyzer.generate_thumbnail(out_path_long, text=long_text)
    assert thumbnail_analyzer.validate_thumbnail(out_path_long)["width"] == 1280

def test_generate_thumbnail_arrow_and_circle(tmp_path):
    """検証: 矢印とサークルを描画したときの動作検証"""
    out_path = tmp_path / "decorations.png"
    thumbnail_analyzer.generate_thumbnail(out_path, draw_arrow=True, draw_circle=True)
    res = thumbnail_analyzer.validate_thumbnail(out_path)
    assert res["width"] == 1280
