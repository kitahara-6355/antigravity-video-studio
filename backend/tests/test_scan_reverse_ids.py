import tempfile
import pytest
from pathlib import Path
from tests.scratch.scan_reverse_ids import scan_content_for_reverse_ids, scan_file_for_reverse_ids

def test_scan_content_empty():
    results = scan_content_for_reverse_ids("")
    assert len(results) == 0

def test_scan_content_no_classes():
    results = scan_content_for_reverse_ids("def hello(): pass")
    assert len(results) == 0

def test_scan_content_class_no_ids():
    content = """
class TestE2E1G1:
    def test_something(self):
        assert True
"""
    results = scan_content_for_reverse_ids(content)
    assert len(results) == 1
    assert results[0][0] == "TestE2E1G1"
    assert results[0][1] == []
    assert results[0][2] == 0

def test_scan_content_class_with_ids():
    content = """
class TestE2E1G1InitialDisplay:
    # Test for reverse IDs
    def test_one(self):
        # story: O1-L1-01
        pass
    def test_two(self):
        # story: O8-L1-02
        pass
"""
    results = scan_content_for_reverse_ids(content)
    assert len(results) == 1
    assert results[0][0] == "TestE2E1G1InitialDisplay"
    assert results[0][1] == ["O1", "O8"]
    assert results[0][2] == 2

def test_scan_file_integration():
    content = """
class TestE2EDummy:
    # story: A2-L1-01
    pass
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write(content)
        temp_path = Path(f.name)
    try:
        results = scan_file_for_reverse_ids(temp_path)
        assert len(results) == 1
        assert results[0][0] == "TestE2EDummy"
        assert results[0][1] == ["A2"]
        assert results[0][2] == 1
    finally:
        if temp_path.exists():
            temp_path.unlink()

def test_scan_content_multiple_classes():
    content = """
class ClassOne:
    # story: O1-L1-01
    pass
class ClassTwo:
    # story: A2-L1-02
    pass
"""
    results = scan_content_for_reverse_ids(content)
    assert len(results) == 2
    assert results[0][0] == "ClassOne"
    assert results[0][1] == ["O1"]
    assert results[1][0] == "ClassTwo"
    assert results[1][1] == ["A2"]

import runpy
from unittest.mock import patch, mock_open

def test_main_block_file_exists(capsys):
    script_path = str(Path(__file__).parent / "scratch" / "scan_reverse_ids.py")
    dummy_content = """
class TestWithIds:
    # story: O1-L1-01
    pass

class TestWithNoIds:
    def test_func(self):
        pass
"""
    with patch("pathlib.Path.exists", return_value=True), patch("builtins.open", mock_open(read_data=dummy_content)):
        runpy.run_path(script_path, run_name="__main__")
        
    captured = capsys.readouterr()
    assert "Total classes found: 2" in captured.out
    assert "TestWithIds" in captured.out
    assert "Stories ['O1'] (ID Count: 1)" in captured.out
    assert "TestWithNoIds" in captured.out
    assert "No formal reverse IDs found" in captured.out

def test_main_block_file_not_exists(capsys):
    script_path = str(Path(__file__).parent / "scratch" / "scan_reverse_ids.py")
    with patch("pathlib.Path.exists", return_value=False):
        runpy.run_path(script_path, run_name="__main__")
        
    captured = capsys.readouterr()
    assert "Target path not found:" in captured.out

# --- 新規追加テストケース ---

def test_scan_content_class_indented():
    """インデントされたクラス定義や空白行の揺らぎがある場合のパーステスト"""
    content = """
    class IndentedClass:
        # story: O1-L1-01
        pass
    class AnotherIndentedClass(BaseClass):
        # story: A2-L2-02
        pass
"""
    results = scan_content_for_reverse_ids(content)
    assert len(results) == 2
    assert results[0][0] == "IndentedClass"
    assert results[0][1] == ["O1"]
    assert results[1][0] == "AnotherIndentedClass"
    assert results[1][1] == ["A2"]

def test_scan_file_not_found(caplog):
    """存在しないファイルを指定した場合に安全に空リストを返すテスト"""
    import logging
    non_existent_path = Path("this_file_should_not_exist_at_all_12345.py")
    with caplog.at_level(logging.ERROR):
        results = scan_file_for_reverse_ids(non_existent_path)
    assert results == []
    assert f"Error reading file {non_existent_path}" in caplog.text

def test_scan_file_decode_error():
    """UTF-8でデコードできないバイナリファイルを指定した場合に安全に空リストを返すテスト"""
    with tempfile.NamedTemporaryFile(suffix=".bin", mode="wb", delete=False) as f:
        # UTF-8でデコード不可能な非ASCIIバイナリデータ
        f.write(b"\xff\xfe\x00\xff")
        temp_path = Path(f.name)
    try:
        results = scan_file_for_reverse_ids(temp_path)
        assert results == []
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_scan_file_permission_error(caplog):
    """ファイルパーミッションエラー時の安全なハンドリングテスト"""
    import logging
    dummy_path = Path("permission_denied_file.py")
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with caplog.at_level(logging.ERROR):
            results = scan_file_for_reverse_ids(dummy_path)
    assert results == []
    assert f"Error reading file {dummy_path}" in caplog.text
    assert "Permission denied" in caplog.text

# --- サムネイル生成・品質検証・タスク処理の直接テスト ---

import json
from tests.scratch.scan_reverse_ids import generate_thumbnail, validate_thumbnail, resolve_thumbnail_task

def test_generate_and_validate_thumbnail_success(tmp_path):
    out_file = tmp_path / "thumb_ok.png"
    generate_thumbnail(out_file, 1280, 720, "Success Test")
    assert out_file.exists()
    
    result = validate_thumbnail(out_file)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0

def test_validate_thumbnail_invalid_res(tmp_path):
    out_file = tmp_path / "thumb_invalid_res.png"
    generate_thumbnail(out_file, 640, 360, "Low Res")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(out_file)

def test_validate_thumbnail_invalid_aspect(tmp_path):
    out_file = tmp_path / "thumb_invalid_aspect.png"
    generate_thumbnail(out_file, 1280, 960, "Invalid Aspect")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(out_file)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task(tmp_path):
    class DummyService:
        def __init__(self, output_dir):
            self.output_dir = output_dir
            self.width = 1280
            self.height = 720
            self.text = "Async Task"
            
    service = DummyService(str(tmp_path))
    result_str = await resolve_thumbnail_task(service, "task_async_ok")
    result = json.loads(result_str)
    assert result["width"] == 1280
    assert result["height"] == 720


def test_generate_thumbnail_closes_image_object():
    """generate_thumbnail が Image オブジェクトを正常にクローズすることの検証"""
    from PIL import Image
    from unittest.mock import MagicMock
    
    mock_image = MagicMock(spec=Image.Image)
    mock_image.__enter__.return_value = mock_image
    
    def mock_exit(exc_type, exc_val, exc_tb):
        mock_image.close()
        return False
    mock_image.__exit__.side_effect = mock_exit
    
    with patch("PIL.Image.new", return_value=mock_image), patch("PIL.ImageDraw.Draw"):
        with patch("pathlib.Path.mkdir"), patch("pathlib.Path.unlink"), patch("pathlib.Path.rename"):
            generate_thumbnail("dummy_output.png")
            
    mock_image.close.assert_called_once()


def test_generate_thumbnail_closes_image_object_on_exception():
    """generate_thumbnail 内で例外が発生した場合も Image オブジェクトがクローズされることの検証"""
    from PIL import Image
    from unittest.mock import MagicMock
    
    mock_image = MagicMock(spec=Image.Image)
    mock_image.__enter__.return_value = mock_image
    
    def mock_exit(exc_type, exc_val, exc_tb):
        mock_image.close()
        return False
    mock_image.__exit__.side_effect = mock_exit
    mock_image.save.side_effect = Exception("Save failed")
    
    with patch("PIL.Image.new", return_value=mock_image), patch("PIL.ImageDraw.Draw"):
        with patch("pathlib.Path.mkdir"):
            with pytest.raises(Exception, match="Save failed"):
                generate_thumbnail("dummy_output.png")
                
    mock_image.close.assert_called_once()


def test_generate_thumbnail_invalid_type():
    """width または height に整数以外の型や無効な値が指定された場合の検証"""
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail("dummy.png", width="invalid")


def test_generate_thumbnail_non_positive():
    """width または height に 0 以下の値が指定された場合の検証"""
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail("dummy.png", width=-10)


def test_generate_thumbnail_overwrite_existing(tmp_path):
    """出力ファイルが既に存在する場合に正しく上書きされるかの検証"""
    out_file = tmp_path / "thumb_overwrite.png"
    out_file.write_text("dummy")
    assert out_file.exists()
    generate_thumbnail(out_file, 1280, 720, "Overwrite Test")
    assert out_file.exists()
    validate_thumbnail(out_file)


def test_generate_thumbnail_exception_cleanup_and_unlink_fail(tmp_path):
    """画像保存例外時のクリーンアップ処理および一時ファイル削除でエラーが発生した場合の検証"""
    out_file = tmp_path / "thumb_fail_cleanup.png"
    
    with patch("PIL.Image.Image.save", side_effect=RuntimeError("Save Error")):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.unlink", side_effect=OSError("Unlink Error")) as mock_unlink:
                with pytest.raises(RuntimeError, match="Save Error"):
                    generate_thumbnail(out_file, 1280, 720, "Fail Cleanup Test")
                mock_unlink.assert_called()


def test_validate_thumbnail_file_not_found():
    """存在しないファイルを検証した場合に FileNotFoundError になるかの検証"""
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        validate_thumbnail("non_existent_file_12345.png")


def test_validate_thumbnail_too_large(tmp_path):
    """4MB を超えるサイズのファイルを検証した場合に ValueError になるかの検証"""
    out_file = tmp_path / "large_thumb.png"
    out_file.write_text("dummy")
    
    class MockStat:
        def __init__(self):
            self.st_size = 5 * 1024 * 1024
            self.st_mode = 32768  # stat.S_IFREG
            
    with patch("pathlib.Path.stat", return_value=MockStat()):
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(out_file)


def test_validate_thumbnail_verify_corrupted(tmp_path):
    """画像データではない破損ファイルを検証した場合に ValueError になるかの検証"""
    out_file = tmp_path / "corrupted.png"
    out_file.write_text("not an image data")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(out_file)


def test_validate_thumbnail_load_corrupted(tmp_path):
    """load() 呼び出し時に例外が発生する場合に ValueError になるかの検証"""
    out_file = tmp_path / "thumb_load_fail.png"
    generate_thumbnail(out_file, 1280, 720, "Load Fail Test")
    
    with patch("PIL.Image.Image.load", side_effect=RuntimeError("Load Error")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(out_file)




# --- 追加新規テストケース ---

def test_scan_file_is_directory(tmp_path):
    """ディレクトリのパスを指定した場合に安全に空リストを返すテスト"""
    results = scan_file_for_reverse_ids(tmp_path)
    assert results == []


def test_validate_thumbnail_target_is_directory(tmp_path):
    """ディレクトリのパスを指定した場合に ValueError が発生することの検証"""
    with pytest.raises(ValueError, match="Target path is not a file"):
        validate_thumbnail(tmp_path)


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_exception(tmp_path):
    """非同期タスク処理で例外が発生した場合に安全にエラーJSONが返却されることの検証"""
    class ErrorService:
        def __init__(self, output_dir):
            self.output_dir = output_dir
            # 幅に不正な文字列を指定して generate_thumbnail で ValueError を発生させる
            self.width = "invalid_width"
            self.height = 720
            self.text = "Error Test"

    service = ErrorService(str(tmp_path))
    result_str = await resolve_thumbnail_task(service, "task_async_err")
    
    import json
    result = json.loads(result_str)
    assert "error" in result
    assert "task_async_err" in result["task_id"]


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_exception_unhandled(tmp_path):
    """非同期タスク処理で予期しない例外(TypeError)が発生した場合に安全にエラーJSONが返却されることの検証"""
    class TypeErrorService:
        def __init__(self, output_dir):
            self.output_dir = output_dir
            # 幅にNoneを指定して、generate_thumbnail内でTypeErrorを誘発させる
            self.width = None
            self.height = 720
            self.text = "TypeError Test"

    service = TypeErrorService(str(tmp_path))
    result_str = await resolve_thumbnail_task(service, "task_async_type_err")
    
    result = json.loads(result_str)
    assert "error" in result
    assert "task_async_type_err" in result["task_id"]


def test_generate_thumbnail_unhandled_exception_cleanup(tmp_path):
    """generate_thumbnail内で予期しない例外(Exception)が発生した際にも一時ファイルがクリーンアップされることの検証"""
    out_file = tmp_path / "thumb_unhandled_fail.png"
    
    # img.saveの呼び出し時に予期しない任意の例外を発生させる
    with patch("PIL.Image.Image.save", side_effect=Exception("Unexpected Pillow Error")):
        with pytest.raises(Exception, match="Unexpected Pillow Error"):
            generate_thumbnail(out_file, 1280, 720, "Unhandled Exception Cleanup Test")
            
    # 一時ファイル(*.tmp)が残っていないことを検証する
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
