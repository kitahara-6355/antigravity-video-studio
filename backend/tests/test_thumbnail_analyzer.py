# -*- coding: utf-8 -*-
import sys
import os
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image
import io
from unittest.mock import patch, MagicMock

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.services.thumbnail_analyzer import ThumbnailAnalyzer, thumbnail_analyzer

def test_generate_thumbnail_success(tmp_path):
    """正常系: 適切な解像度(1280x720)とアスペクト比(16:9)で画像が生成され、品質検証に合格すること"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_normal.png"
    
    # 正常な生成
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=1280,
        height=720,
        text="テストサムネイル\n高品質画像処理",
        draw_arrow=True,
        draw_circle=True,
        use_banner=True
    )
    
    assert res_path.exists()
    assert res_path == output_file
    
    # 画像のロード検証
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1280, 720)
        assert img.format == "PNG"
        
    # ファイルサイズ検証 (4MB未満)
    size_bytes = res_path.stat().st_size
    assert size_bytes > 0
    assert size_bytes < 4 * 1024 * 1024
    
    # validate_thumbnailによる検証
    val_res = analyzer.validate_thumbnail(res_path)
    assert val_res["width"] == 1280
    assert val_res["height"] == 720
    assert val_res["size_bytes"] == size_bytes

def test_generate_thumbnail_jpeg_success(tmp_path):
    """正常系: JPEG形式での出力検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_normal.jpg"
    
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=1920,
        height=1080,
        text="JPEG高解像度テスト",
        draw_arrow=False,
        draw_circle=False,
        use_banner=False
    )
    
    assert res_path.exists()
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1920, 1080)
        assert img.format == "JPEG"
        
    # validate_thumbnailによる検証
    val_res = analyzer.validate_thumbnail(res_path)
    assert val_res["width"] == 1920
    assert val_res["height"] == 1080

def test_generate_thumbnail_invalid_resolutions(tmp_path):
    """解像度検証: 1280x720未満、または極端に大きいサイズ(8K超)でエラーが発生すること"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 1280x720未満 (例: 640x360) -> エラー
    output_file = tmp_path / "test_small.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=640, height=360)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)
    
    # 2. 8K超 (例: 7681x4320) -> エラー
    output_file2 = tmp_path / "test_huge.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file2, width=7681, height=4320)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)

def test_generate_thumbnail_invalid_aspect_ratio(tmp_path):
    """アスペクト比検証: 16:9でない場合にエラーが発生すること"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_aspect.png"
    
    # 1280x960 は 4:3 -> エラー
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=1280, height=960)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

def test_generate_thumbnail_invalid_inputs(tmp_path):
    """入力エラー検証: 無効なパラメータに対するエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 出力パスが空
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail("", width=1280, height=720)
    assert "Output path must not be empty" in str(excinfo.value)
    
    # 2. 出力パスがディレクトリ
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(tmp_path, width=1280, height=720)
    assert "must be a file path, not a directory" in str(excinfo.value)
    
    # 3. サポート外の拡張子 (例: .gif)
    output_file = tmp_path / "test.gif"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=1280, height=720)
    assert "Unsupported file format" in str(excinfo.value)

def test_validate_thumbnail_corrupted(tmp_path):
    """画像検証: 破損画像や空ファイルに対する validate_thumbnail の挙動"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        analyzer.validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. 空ファイル
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(empty_file)
    assert "is empty" in str(excinfo.value)
    
    # 3. 破損データ (中身が不適切な画像データ)
    corrupt_file = tmp_path / "corrupt.png"
    corrupt_file.write_bytes(b"this is not a valid png image data")
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(corrupt_file)
    err_str = str(excinfo.value)
    assert "verify failed" in err_str or "Failed to load image pixels" in err_str or "header is not PNG" in err_str

def test_validate_thumbnail_aspect_ratios_comprehensive(tmp_path):
    """アスペクト比検証: 16:9以外の様々なアスペクト比での検証エラー"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 4:3 (例: 1440x1080) -> エラー
    file_4_3 = tmp_path / "thumb_4_3.png"
    img = Image.new("RGB", (1440, 1080), color=(255, 0, 0))
    img.save(file_4_3, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_4_3)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)
    
    # 2. 1:1 (例: 1280x1280) -> エラー
    file_1_1 = tmp_path / "thumb_1_1.png"
    img = Image.new("RGB", (1280, 1280), color=(255, 0, 0))
    img.save(file_1_1, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_1_1)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

    # 3. 境界値誤差テスト: 誤差 0.02 (例: 1295x720 -> 比率 1.7986, 16:9 は 1.7778 -> 差は 0.0208) -> エラー
    file_border_fail = tmp_path / "thumb_border_fail.png"
    img = Image.new("RGB", (1295, 720), color=(255, 0, 0))
    img.save(file_border_fail, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_border_fail)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

    # 4. 許容される境界誤差テスト: 誤差 0.0097 (例: 1287x720 -> 比率 1.7875, 差は 0.0097) -> パス
    file_border_pass = tmp_path / "thumb_border_pass.png"
    img = Image.new("RGB", (1287, 720), color=(255, 0, 0))
    img.save(file_border_pass, "PNG")
    img.close()
    res = analyzer.validate_thumbnail(file_border_pass)
    assert res["width"] == 1287
    assert res["height"] == 720

def test_validate_thumbnail_file_size_boundaries(tmp_path):
    """ファイルサイズ検証: 4MB境界値などの検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 4MBを超える巨大なファイル（擬似的にモックサイズを指定するか、ダミーファイルを生成）
    large_file = tmp_path / "large_mock.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(large_file, "PNG")
    img.close()
    
    # st_size を 4MB以上にモック
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 + 1
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(large_file)
        assert "exceeds 4MB" in str(excinfo.value)

def test_validate_thumbnail_extreme_resolutions_comprehensive(tmp_path):
    """解像度検証: 下限・上限、および非数値等の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 下限未満 (例: 1279x719) -> エラー
    file_low = tmp_path / "thumb_low.png"
    img = Image.new("RGB", (1279, 719), color=(255, 0, 0))
    img.save(file_low, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_low)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)
    
    # 2. 8K上限超 (例: 7682x4321) -> エラー
    file_high = tmp_path / "thumb_high.png"
    img = Image.new("RGB", (7682, 4321), color=(255, 0, 0))
    img.save(file_high, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_high)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_integration(tmp_path):
    """非同期タスク処理: resolve_thumbnail_task のインテグレーション検証"""
    analyzer = ThumbnailAnalyzer()
    db_file = tmp_path / "test_thumb.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_thumb_001"
    
    # Agentモック
    agent = MagicMock()
    agent.output_dir = output_dir
    agent.db_path = str(db_file)
    agent.width = 1280
    agent.height = 720
    agent.text = "非同期タスクテストサムネイル"
    
    # 非同期実行
    result_json = await analyzer.resolve_thumbnail_task(agent, task_id)
    result_data = json.loads(result_json)
    
    assert result_data["valid"] is True
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    
    expected_path = output_dir / f"{task_id}.png"
    assert expected_path.exists()
    assert Path(result_data["path"]) == expected_path
    
    # DBのレコード確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        db_task_id, db_path, db_width, db_height, db_size = row
        assert db_task_id == task_id
        assert Path(db_path) == expected_path
        assert db_width == 1280
        assert db_height == 720
        assert db_size == expected_path.stat().st_size
    finally:
        conn.close()


def test_generate_thumbnail_invalid_types(tmp_path):
    """異常系: 非数値やNone値などの無効な解像度パラメータが渡された際のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_invalid_type.png"
    
    # width が None -> デフォルトの1280x720が使われ、正常生成
    res_path = analyzer.generate_thumbnail(output_file, width=None, height=720)
    assert res_path.exists()
    
    # width が非数値文字列 -> ValueError
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width="invalid_width", height=720)
    assert "must be integers" in str(excinfo.value)


def test_generate_thumbnail_aspect_ratio_boundary(tmp_path):
    """解像度・アスペクト比検証: アスペクト比の誤差境界値の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 誤差 0.01 以下のギリギリのアスペクト比 (例: 1281x720 は 1.779、16:9 は 1.778 -> 差は 0.001 で許容)
    output_file = tmp_path / "test_boundary.png"
    res_path = analyzer.generate_thumbnail(output_file, width=1281, height=720)
    assert res_path.exists()
    
    # 誤差 0.01 を超えるアスペクト比 (例: 1300x720 は 1.806 -> 差は 0.028 でエラー)
    output_file2 = tmp_path / "test_boundary_fail.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file2, width=1300, height=720)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)


def test_generate_thumbnail_write_error(tmp_path):
    """異常系: 存在しないディレクトリパスなど、書き込み不可のディレクトリを指定した場合のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 通常、generate_thumbnail は mkdir(parents=True) するので自動作成されるが、
    # もし親ディレクトリがファイルとして既に存在する場合、mkdir は OSError となる。
    dummy_file = tmp_path / "already_a_file"
    dummy_file.write_text("just a file")
    
    output_file_fail = dummy_file / "test.png"
    with pytest.raises(IOError) as excinfo:
        analyzer.generate_thumbnail(output_file_fail, width=1280, height=720)
    assert "Cannot write thumbnail" in str(excinfo.value) or "Cannot create parent directory" in str(excinfo.value)


def test_validate_thumbnail_resolution_boundary(tmp_path):
    """validate_thumbnail検証: 許容解像度上限(8K)および下限(1280x720)の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 8K解像度上限テスト
    output_file = tmp_path / "test_8k.png"
    
    # ダミーの巨大なPNGファイルを生成 (PILで作成)
    img = Image.new("RGB", (7681, 4320), color=(255, 0, 0))
    img.save(output_file, "PNG")
    img.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(output_file)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)
    
    # 2. 1280x720下限テスト
    output_file2 = tmp_path / "test_low.png"
    img2 = Image.new("RGB", (1279, 720), color=(255, 0, 0))
    img2.save(output_file2, "PNG")
    img2.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(output_file2)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)

