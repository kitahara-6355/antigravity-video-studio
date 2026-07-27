import pytest
from pathlib import Path
from backend.verify_image_gen import generate_image, validate_generated_image

@pytest.fixture
def temp_output_dir(tmp_path):
    """pytestの一時ディレクトリfixtureを利用してテスト用フォルダを用意"""
    return tmp_path

def test_generate_image_success(temp_output_dir):
    """正常系: 16:9 の高品質画像が正常に生成され、検証をパスすることを確認"""
    output_path = temp_output_dir / "test_image.png"
    
    res_path = generate_image(
        output_path=output_path,
        width=1280,
        height=720,
        text="Hello Unit Test",
        is_preview=False,
        strict_quality=True
    )
    
    assert res_path.exists()
    assert res_path == output_path
    
    # 画像の検証
    info = validate_generated_image(res_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0
    assert Path(info["path"]) == res_path

def test_generate_image_preview_mode(temp_output_dir):
    """正常系: プレビューモードでのウォーターマークやカメラレティクル付き画像の生成"""
    output_path = temp_output_dir / "test_preview.png"
    
    res_path = generate_image(
        output_path=output_path,
        width=1920,
        height=1080,
        text="Preview Mode Test",
        is_preview=True,
        strict_quality=True
    )
    
    assert res_path.exists()
    info = validate_generated_image(res_path)
    assert info["width"] == 1920
    assert info["height"] == 1080

def test_generate_image_invalid_dimensions(temp_output_dir):
    """異常系: 解像度やアスペクト比、負の値が与えられた場合に適切な例外が発生することを確認"""
    output_path = temp_output_dir / "test_invalid.png"
    
    # アスペクト比違反
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_image(output_path, width=1600, height=1200, strict_quality=True)
        
    # 最低解像度を下回る
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_image(output_path, width=640, height=360, strict_quality=True)

    # 負の解像度
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_image(output_path, width=-1280, height=720)

def test_validate_image_failures(temp_output_dir):
    """異常系: 存在しない、空、破損したファイルを検証したときに例外が発生することを確認"""
    # 存在しないファイル
    non_existent = temp_output_dir / "non_existent.png"
    with pytest.raises(FileNotFoundError):
        validate_generated_image(non_existent)
        
    # 空のファイル
    empty_file = temp_output_dir / "empty.png"
    empty_file.touch()
    with pytest.raises(ValueError, match="File is empty or too small"):
        validate_generated_image(empty_file)

    # 破損した画像ファイル
    corrupt_file = temp_output_dir / "corrupt.png"
    corrupt_file.write_bytes(b"corrupt image content")
    with pytest.raises(ValueError, match="Image verification failed"):
        validate_generated_image(corrupt_file)

def test_validate_image_aspect_ratio_fail(temp_output_dir):
    """異常系: strict_quality=Falseで生成した4:3画像をvalidate_generated_imageで検証したときにアスペクト比違反を検知することを確認"""
    output_path = temp_output_dir / "test_4_3.png"
    
    # クオリティ制限なしで 4:3 画像を生成
    generate_image(output_path, width=1600, height=1200, strict_quality=False)
    
    # validate_generated_imageは常に16:9アスペクト比を要求するため、検証エラーになるはず
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_generated_image(output_path)
