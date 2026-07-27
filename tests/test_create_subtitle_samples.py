import os
from pathlib import Path
import pytest
from unittest import mock
from PIL import Image, ImageFont

from backend.create_subtitle_samples import (
    create_subtitle_sample,
    create_integrated_sample,
)

def test_create_subtitle_sample_custom_path(tmp_path):
    # カスタムパスを指定して字幕サンプル画像を生成
    output_file = tmp_path / "custom_subtitle.png"
    result_path = create_subtitle_sample(output_path=str(output_file))
    
    assert result_path == str(output_file)
    assert output_file.exists()
    
    # 画像が正しくオープンできるか検証
    with Image.open(output_file) as img:
        assert img.size == (1920, 1080)
        assert img.mode == "RGB"

def test_create_subtitle_sample_default_path():
    # デフォルトパス（output_path=None）での字幕サンプル生成
    expected_path = Path("backend/subtitle_sample.png")
    
    # 事前にファイルが存在した場合は削除しておく
    if expected_path.exists():
        expected_path.unlink()
        
    try:
        result_path = create_subtitle_sample(output_path=None)
        assert result_path.lower() == str(expected_path.resolve()).lower()
        assert expected_path.exists()
    finally:
        # テスト後にファイルを確実にクリーンアップ
        if expected_path.exists():
            expected_path.unlink()

def test_create_integrated_sample_custom_path(tmp_path):
    # カスタムパスを指定して統合サンプル画像を生成
    output_file = tmp_path / "custom_integrated.png"
    result_path = create_integrated_sample(output_path=str(output_file))
    
    assert result_path == str(output_file)
    assert output_file.exists()
    
    # 画像が正しくオープンできるか検証
    with Image.open(output_file) as img:
        assert img.size == (1920, 1080)
        assert img.mode == "RGB"

def test_create_integrated_sample_default_path():
    # デフォルトパス（output_path=None）での統合サンプル生成
    expected_path = Path("backend/B_plan_with_subtitle.png")
    
    # 事前にファイルが存在した場合は削除しておく
    if expected_path.exists():
        expected_path.unlink()
        
    try:
        result_path = create_integrated_sample(output_path=None)
        assert result_path.lower() == str(expected_path.resolve()).lower()
        assert expected_path.exists()
    finally:
        # テスト後にファイルを確実にクリーンアップ
        if expected_path.exists():
            expected_path.unlink()

def test_font_loading_success_mock(tmp_path):
    # ImageFont.truetype が成功するケースをシミュレート（28-29行目, 90-92行目のカバレッジ用）
    real_default_font = ImageFont.load_default()
    
    with mock.patch("PIL.ImageFont.truetype", return_value=real_default_font):
        output_file1 = tmp_path / "success_subtitle.png"
        output_file2 = tmp_path / "success_integrated.png"
        
        result1 = create_subtitle_sample(output_path=str(output_file1))
        assert result1 == str(output_file1)
        assert output_file1.exists()
        
        result2 = create_integrated_sample(output_path=str(output_file2))
        assert result2 == str(output_file2)
        assert output_file2.exists()

def test_font_loading_exception_fallback(tmp_path):
    # ImageFont.truetype が例外を投げたときのフォールバック検証
    output_file1 = tmp_path / "fallback_subtitle.png"
    output_file2 = tmp_path / "fallback_integrated.png"
    
    # 事前に本物のデフォルトフォントをロードしておく
    real_default_font = ImageFont.load_default()
    
    # ImageFont.truetypeで例外を投げるようにモックし、load_defaultは取得済みの本物デフォルトフォントを返すようにする
    with mock.patch("PIL.ImageFont.truetype", side_effect=OSError("Font error")):
        with mock.patch("PIL.ImageFont.load_default", return_value=real_default_font):
            # create_subtitle_sample の実行
            result1 = create_subtitle_sample(output_path=str(output_file1))
            assert result1 == str(output_file1)
            assert output_file1.exists()
            
            # create_integrated_sample の実行
            result2 = create_integrated_sample(output_path=str(output_file2))
            assert result2 == str(output_file2)
            assert output_file2.exists()

def test_main_block():
    # スクリプトのメインブロックの動作確認
    path1 = Path("backend/subtitle_sample.png")
    path2 = Path("backend/B_plan_with_subtitle.png")
    
    for path in [path1, path2]:
        if path.exists():
            path.unlink()
            
    # compile() を使用して、ファイルパスと紐付けたコードオブジェクトを生成して exec
    script_path = Path("backend/create_subtitle_samples.py").resolve()
    with open(script_path, "r", encoding="utf-8") as f:
        code_str = f.read()
        
    code_obj = compile(code_str, str(script_path), "exec")
    
    global_dict = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    
    try:
        with mock.patch("builtins.print") as mock_print:
            exec(code_obj, global_dict)
            mock_print.assert_called()
    finally:
        # 生成されたファイルをクリーンアップ
        for path in [path1, path2]:
            if path.exists():
                path.unlink()
