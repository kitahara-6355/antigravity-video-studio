import io
import os
import sys
import json
import runpy
from unittest.mock import patch, mock_open, MagicMock
import pytest
from pathlib import Path
from PIL import Image

# sys.path に backend_dir を追加
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from tests.scratch.find_classes import (
    main,
    find_classes_in_file,
    generate_find_classes_thumbnail,
    validate_thumbnail,
    resolve_find_classes_task,
    OUTPUT_DIR,
)

def run_find_classes(args=None):
    """find_classes.py を直接実行し、その標準出力をキャプチャして返す"""
    captured_output = io.StringIO()
    if args is None:
        args = []
    
    with patch("sys.argv", ["find_classes.py"] + args):
        with patch("sys.stdout", new=captured_output):
            try:
                main()
            except SystemExit:
                pass
    return captured_output.getvalue()


def test_find_classes_multiple_classes():
    """正常系: 複数のクラス定義がある場合、正しく抽出されること"""
    content = (
        "import sys\n"
        "class MyClassA:\n"
        "    def method(self):\n"
        "        pass\n"
        "\n"
        "class MyClassB:\n"
        "    pass\n"
    )
    with patch("builtins.open", mock_open(read_data=content)) as mock_file:
        output = run_find_classes()

        # openされた引数の検証
        # 2026-07-26: 以前は別ワークツリーの Windows 絶対パスを直書きしていたが、
        # 実装がリポジトリ相対で解決するようになったため、実装側の定数と突き合わせる。
        # パスをテストに直書きすると環境が変わるたびに壊れる。
        import find_classes as _fc
        mock_file.assert_called_once_with(
            _fc.DEFAULT_PATH,
            "r",
            encoding="utf-8"
        )

        # 出力の検証
        assert "Line     2: MyClassA" in output
        assert "Line     6: MyClassB" in output


def test_find_classes_no_classes():
    """正常系: クラス定義がない場合、何も出力されないこと"""
    content = (
        "import sys\n"
        "def hello():\n"
        "    print('hello')\n"
    )
    with patch("builtins.open", mock_open(read_data=content)):
        output = run_find_classes()
        assert "No classes found or file does not exist." in output


def test_find_classes_indented_class():
    """エッジケース: インデントされたクラス定義は抽出対象外になること"""
    content = (
        "class RootClass:\n"
        "    class InnerClass:\n"
        "        pass\n"
    )
    with patch("builtins.open", mock_open(read_data=content)):
        output = run_find_classes()
        assert "Line     1: RootClass" in output
        # InnerClassは行頭開始ではないため、抽出されない
        assert "InnerClass" not in output


def test_find_classes_commented_class():
    """エッジケース: コメントアウトされたクラス定義は抽出されないこと"""
    content = (
        "# class CommentedClassA:\n"
        "  # class CommentedClassB:\n"
        "class ActiveClass:\n"
        "    pass\n"
    )
    with patch("builtins.open", mock_open(read_data=content)):
        output = run_find_classes()
        assert "CommentedClassA" not in output
        assert "CommentedClassB" not in output
        assert "Line     3: ActiveClass" in output


def test_find_classes_special_names():
    """エッジケース: 特殊な文字（アンダースコアや数字）を含むクラス名が正しく抽出されること"""
    content = (
        "class _PrivateClass:\n"
        "    pass\n"
        "class ClassWithNumbers123:\n"
        "    pass\n"
        "class Class_With_Underscores:\n"
        "    pass\n"
    )
    with patch("builtins.open", mock_open(read_data=content)):
        output = run_find_classes()
        assert "Line     1: _PrivateClass" in output
        assert "Line     3: ClassWithNumbers123" in output
        assert "Line     5: Class_With_Underscores" in output


def test_find_classes_invalid_syntax():
    """エッジケース: 正規表現にマッチしない無効なクラス定義は抽出されないが、
    正規表現上マッチしてしまう無効な識別子は抽出されることを検証 (プロダクションコードの制限事項)
    """
    content = (
        "classmyclass:\n"  # スペースがないためマッチしない
        "    pass\n"
        "class 123Class:\n" # Python of 識別子としては無効だが、\w+にはマッチするため抽出される
        "    pass\n"
        "class :\n"        # \w+にマッチする文字がないためマッチしない
        "    pass\n"
    )
    with patch("builtins.open", mock_open(read_data=content)):
        output = run_find_classes()
        assert "Line     3: 123Class" in output
        assert "classmyclass" not in output
        assert "class :" not in output


def test_find_classes_file_not_found():
    """異常系: ファイルが存在しない場合に FileNotFoundError が送出されること"""
    with patch("builtins.open", side_effect=FileNotFoundError("Mocked file not found")):
        with pytest.raises(FileNotFoundError) as exc_info:
            run_find_classes()
        assert "Mocked file not found" in str(exc_info.value)


def test_find_classes_unicode_decode_error():
    """異常系: エンコーディングエラーが発生した場合に UnicodeDecodeError が送出されること"""
    with patch("builtins.open", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "Mocked decode error")):
        with pytest.raises(UnicodeDecodeError) as exc_info:
            run_find_classes()
        assert "Mocked decode error" in str(exc_info.value)


# --- 追加のカバレッジ向上テスト ---

def test_find_classes_in_file_not_exists():
    """正常系/異常系: ファイルが存在しない場合は空リストを返すこと"""
    res = find_classes_in_file("non_existent_file_xyz.py")
    assert res == []


def test_main_with_path_argument(tmp_path):
    """正常系: 引数として有効なパスが渡された場合、そのファイルをスキャンすること"""
    test_file = tmp_path / "test_target.py"
    test_file.write_text("class TargetClass:\n    pass\n", encoding="utf-8")
    
    output = run_find_classes([str(test_file)])
    assert f"Scanning: {test_file}" in output
    assert "Line     1: TargetClass" in output


def test_main_with_path_argument_no_classes(tmp_path):
    """正常系: 引数で渡されたファイルが存在するがクラスがない場合"""
    test_file = tmp_path / "test_target_empty.py"
    test_file.write_text("def hello(): pass\n", encoding="utf-8")
    
    output = run_find_classes([str(test_file)])
    assert "No classes found or file does not exist." in output


def test_run_as_main_block(tmp_path):
    """正常系: スクリプトとして直接実行された場合（__main__ブロック）の動作確認"""
    test_file = tmp_path / "test_target_main.py"
    test_file.write_text("class MainBlockClass:\n    pass\n", encoding="utf-8")
    
    script_path = Path(__file__).parent / "find_classes.py"
    
    with patch("sys.argv", ["find_classes.py", str(test_file)]):
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except SystemExit:
            pass


def test_run_as_main_block_exit(tmp_path):
    """正常系: スクリプトとして直接実行された場合（__main__ブロックで終了コードが返ること）"""
    test_file = tmp_path / "test_target_main_exit.py"
    test_file.write_text("class MainBlockClass:\n    pass\n", encoding="utf-8")
    
    script_path = Path(__file__).parent / "find_classes.py"
    
    with patch("sys.argv", ["find_classes.py", str(test_file)]):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(str(script_path), run_name="__main__")
        assert exc_info.value.code == 0


def test_generate_thumbnail_invalid_dimensions(tmp_path):
    """異常系: 幅や高さが整数値でない、または 0 以下の場合に ValueError が発生すること"""
    output_file = tmp_path / "thumb.png"
    
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_find_classes_thumbnail(output_file, width="invalid", height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_find_classes_thumbnail(output_file, width=-100, height=720)

    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_find_classes_thumbnail(output_file, width=1280, height=0)


def test_generate_thumbnail_success_and_overwrite(tmp_path):
    """正常系: サムネイル画像が正常に生成され、既存ファイルがあっても上書き保存されること"""
    output_file = tmp_path / "thumb.png"
    
    # 既存ファイルをあらかじめ作成しておく
    output_file.write_text("dummy", encoding="utf-8")
    
    res_path = generate_find_classes_thumbnail(output_file, width=1280, height=720, text="Test Title")
    assert res_path == output_file
    assert output_file.exists()
    
    # 実際に画像ファイルとして開けるか確認
    with Image.open(output_file) as img:
        assert img.size == (1280, 720)


def test_generate_thumbnail_os_error_cleanup(tmp_path):
    """異常系: 保存時にエラーが発生した場合、一時ファイルがクリーンアップされること"""
    output_file = tmp_path / "error_thumb.png"
    
    with patch.object(Path, "rename", side_effect=OSError("Rename failed")):
        with pytest.raises(OSError, match="Rename failed"):
            generate_find_classes_thumbnail(output_file)
            
    # 一時ファイル (*.tmp) が残っていないことを検証
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_validate_thumbnail_errors(tmp_path):
    """異常系: validate_thumbnail で各種エラーが発生することを検証"""
    non_existent = tmp_path / "not_found.png"
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(non_existent)
        
    # ファイルサイズ超過
    oversized = tmp_path / "oversized.png"
    oversized.touch()
    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024  # 5MB
    with patch.object(Path, "stat", return_value=mock_stat):
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(oversized)
            
    # 画像が破損している（空ファイルなど）
    corrupted = tmp_path / "corrupted.png"
    corrupted.touch()
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupted)
        
    # 解像度不足 (1280x720 未満)
    low_res = tmp_path / "low_res.png"
    img_low = Image.new("RGB", (640, 360), color="blue")
    img_low.save(low_res)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res)
        
    # アスペクト比が 16:9 でない
    bad_aspect = tmp_path / "bad_aspect.png"
    img_bad = Image.new("RGB", (1280, 800), color="blue")  # 16:10
    img_bad.save(bad_aspect)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_aspect)


def test_validate_thumbnail_success(tmp_path):
    """正常系: 正常な画像メタデータを正しく検証・返却すること"""
    valid_file = tmp_path / "valid.png"
    img = Image.new("RGB", (1280, 720), color="green")
    img.save(valid_file)
    
    info = validate_thumbnail(valid_file)
    assert info["path"] == str(valid_file)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0


@pytest.mark.asyncio
async def test_resolve_find_classes_task(tmp_path):
    """正常系: 非同期タスク処理で画像が生成され、結果がJSON文字列で返されること"""
    # OUTPUT_DIR を一時ディレクトリへ差し替える
    temp_output_dir = tmp_path / "temp_thumbnails"
    
    with patch("tests.scratch.find_classes.OUTPUT_DIR", str(temp_output_dir)):
        task_id = "test_async_task_123"
        result_json = await resolve_find_classes_task(task_id)
        
        info = json.loads(result_json)
        expected_path = temp_output_dir / f"{task_id}.png"
        
        assert info["path"] == str(expected_path)
        assert info["width"] == 1280
        assert info["height"] == 720
        assert expected_path.exists()


def test_generate_thumbnail_unlink_os_error(tmp_path):
    """異常系: 保存時にエラーが発生し、かつ一時ファイルの削除(unlink)自体もOSErrorになった場合のハンドリング"""
    output_file = tmp_path / "error_unlink.png"
    
    with patch.object(Path, "rename", side_effect=OSError("Rename failed")):
        with patch.object(Path, "unlink", side_effect=OSError("Unlink failed")):
            with pytest.raises(OSError, match="Rename failed"):
                generate_find_classes_thumbnail(output_file)


def test_validate_thumbnail_load_corrupted_image(tmp_path):
    """異常系: 画像のverifyは通るが、load()で破損が検知された場合に ValueError を投げること"""
    output_file = tmp_path / "load_corrupt.png"
    # まずは正常な画像を生成する
    img = Image.new("RGB", (1280, 720), color="red")
    img.save(output_file)
    
    with patch("PIL.Image.Image.load", side_effect=SyntaxError("Corrupted pixel data")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(output_file)


