import sys
import os
import urllib.request
import urllib.error
import json
import pytest
from unittest.mock import MagicMock, patch

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import backend.check_pipeline_status as check_pipeline_status
from backend.check_pipeline_status import check

def test_check_success_full(capsys):
    # 正常系: すべてのデータが存在するケース
    mock_response = MagicMock()
    mock_data = {
        "status": "completed",
        "current_stage": "publish",
        "stages": [
            {"index": 0, "name": "transcribe", "status": "completed", "detail": "Done"},
            {"stage_index": 1, "stage_name": "optimize", "status": "running", "message": "In progress"},
            {"index": 2, "name": "pending_stage", "status": "pending"},
            {"index": 3, "name": "failed_stage", "status": "failed"},
            {"index": 4, "name": "unknown_stage", "status": "unknown"}
        ],
        "result": {
            "duration_seconds": 120.5,
            "final_path": "/path/to/final/video.mp4",
            "quality_score": 95,
            "stage_results": [
                {"name": "transcribe", "success": True, "duration": 45.2},
                {"name": "optimize", "success": False, "duration": 10.0}
            ],
            "quality_feedback": [
                "Good volume",
                "Needs more contrast"
            ]
        }
    }
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        check_pipeline_status.check()
        
    captured = capsys.readouterr()
    assert "Status:  completed" in captured.out
    assert "Stage:   publish" in captured.out
    assert "✅ [0] transcribe: completed Done" in captured.out
    assert "🔄 [1] optimize: running In progress" in captured.out
    assert "⏳ [2] pending_stage: pending " in captured.out
    assert "❌ [3] failed_stage: failed " in captured.out
    assert "? [4] unknown_stage: unknown " in captured.out
    assert "Duration: 120.5s" in captured.out
    assert "Final:    /path/to/final/video.mp4" in captured.out
    assert "Quality:  95" in captured.out
    assert "✅ transcribe: 45.2s" in captured.out
    assert "❌ optimize: 10.0s" in captured.out
    assert "Quality Feedback:" in captured.out
    assert "- Good volume" in captured.out
    assert "- Needs more contrast" in captured.out

def test_check_success_minimal(capsys):
    # 正常系: 最小限のデータのみ存在するケース
    mock_response = MagicMock()
    mock_data = {
        "status": "pending",
        "current_stage": "transcribe"
    }
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        check_pipeline_status.check()
        
    captured = capsys.readouterr()
    assert "Status:  pending" in captured.out
    assert "Stage:   transcribe" in captured.out
    assert "Duration:" not in captured.out

def test_check_url_error(capsys):
    # 異常系: URLError が発生するケース
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.check()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Failed to connect to pipeline server" in captured.err

def test_check_connection_unexpected_error(capsys):
    # 異常系: 接続中に予期しない例外が発生するケース
    with patch("urllib.request.urlopen", side_effect=RuntimeError("Unexpected socket error")):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.check()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error during connection: Unexpected socket error" in captured.err

def test_check_json_decode_error(capsys):
    # 異常系: 不正なJSONレスポンス
    mock_response = MagicMock()
    mock_response.read.return_value = b"invalid json"
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.check()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Invalid JSON response from server" in captured.err

def test_check_parse_unexpected_error(capsys):
    # 異常系: デコードなどで予期しない例外が発生するケース
    mock_response = MagicMock()
    # デコード時にエラーを起こすように decode メソッドをモック
    mock_bytes = MagicMock()
    mock_bytes.decode.side_effect = AttributeError("Mock decode error")
    mock_response.read.return_value = mock_bytes
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.check()
            
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error during parsing: Mock decode error" in captured.err

def test_check_main_entrypoint(capsys):
    # __name__ == "__main__" ブロックの実行カバー
    mock_response = MagicMock()
    mock_data = {
        "status": "completed",
        "current_stage": "publish"
    }
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        import runpy
        # run_name="__main__" として実行することで、if __name__ == "__main__": が True になる
        runpy.run_module("check_pipeline_status", run_name="__main__")
        
    captured = capsys.readouterr()
    assert "Status:  completed" in captured.out


import tempfile
from pathlib import Path
from PIL import Image

def test_generate_thumbnail_success():
    # 正常系: デフォルト値
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb.png"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1280, 720)

def test_generate_thumbnail_custom_params():
    # 正常系: カスタムサイズ、文字列での指定
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_custom.png"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(
            out_path, width="1920", height="1080", text="Custom Text Test"
        )
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1920, 1080)

def test_generate_thumbnail_invalid_dimensions():
    # 異常系: width/heightが非整数
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_err.png"
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width="abc")
        
        # 異常系: 0 または負の値
        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=0)
        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, height=-100)

def test_generate_thumbnail_save_exception_cleanup():
    # 異常系: 保存中に例外が発生した場合、一時ファイルがクリーンアップされること
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_fail.png"
        with patch("PIL.Image.Image.save", side_effect=RuntimeError("Save failed")):
            with pytest.raises(RuntimeError, match="Save failed"):
                check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
            
            # 一時ファイル (*.tmp) が残っていないことを確認
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0
            assert not out_path.exists()

def test_generate_thumbnail_existing_file_unlink():
    # 正常系: 既にファイルが存在する場合に unlink が呼ばれることを検証 (L123)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "existing_thumb.png"
        out_path.touch()
        assert out_path.exists()
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1280, 720)

def test_generate_thumbnail_unlink_exception():
    # 異常系: 一時ファイル削除中に例外が発生した場合のハンドリング (L127-130)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_unlink_fail.png"
        temp_file_path = out_path.with_suffix(".testuuid.tmp")
        temp_file_path.touch() # 事前に存在させて exists() を True にする
        
        import pathlib
        concrete_class = pathlib.WindowsPath if os.name == "nt" else pathlib.PosixPath
        original_unlink = concrete_class.unlink
        
        def mock_unlink(self, *args, **kwargs):
            if "testuuid.tmp" in self.name:
                raise PermissionError("Mocked permission error during unlink")
            return original_unlink(self, *args, **kwargs)
            
        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "testuuid"
            with patch("PIL.Image.Image.save", side_effect=RuntimeError("Save failed")):
                with patch.object(concrete_class, "unlink", autospec=True, side_effect=mock_unlink):
                    with pytest.raises(RuntimeError, match="Save failed"):
                        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_success():
    # 正常系
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "valid.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        meta = check_pipeline_status.validate_pipeline_status_thumbnail(out_path)
        assert meta["path"] == str(out_path)
        assert meta["width"] == 1280
        assert meta["height"] == 720
        assert meta["size_bytes"] > 0

def test_validate_thumbnail_file_not_found():
    # 異常系: ファイルなし
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        check_pipeline_status.validate_pipeline_status_thumbnail("non_existent_file.png")

def test_validate_thumbnail_size_limit():
    # 異常系: ファイルサイズ超過 (4MB以上)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "large.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value.st_size = 5 * 1024 * 1024 # 5MB
            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_corrupted_verify():
    # 異常系: 画像破損 (verify)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "corrupt_verify.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.verify.side_effect = SyntaxError("Verify error")
            mock_open.return_value.__enter__.return_value = mock_img
            with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_corrupted_load():
    # 異常系: 画像破損 (load)
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "corrupt_load.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.load.side_effect = RuntimeError("Load error")
            mock_img.size = (1280, 720)
            mock_open.return_value.__enter__.return_value = mock_img
            with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_resolution_too_low():
    # 異常系: 解像度不足
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "small.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=1000, height=562)
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_aspect_ratio_mismatch():
    # 異常系: アスペクト比が16:9でない
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "aspect_error.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=1280, height=800)
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_success():
    # 正常系: APIから正常に取得できる場合
    mock_response = MagicMock()
    mock_data = {
        "status": "completed",
        "current_stage": "publish"
    }
    mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_123"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_api_offline():
    # 異常系: API接続失敗時 (タイムアウトやオフライン)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection timed out")):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_offline"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_unexpected_exception():
    # 異常系: asyncio.to_thread 自体が例外をスローする場合のハンドリング (L200-201)
    with patch("asyncio.to_thread", side_effect=RuntimeError("Async task execution error")):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_unexpected"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()

def test_print_result_edge_cases(capsys):
    # result が None または空辞書の場合のテスト (どちらも出力されない)
    check_pipeline_status._print_result(None)
    captured = capsys.readouterr()
    assert captured.out == ""

    check_pipeline_status._print_result({})
    captured = capsys.readouterr()
    assert captured.out == ""

    # 一部のキーが存在し、かつ result が空でない場合のテスト
    check_pipeline_status._print_result({
        "duration_seconds": -10.0,
        "final_path": None,
        "quality_score": -5,
        "stage_results": [],
        "quality_feedback": []
    })
    captured = capsys.readouterr()
    assert "Duration: -10.0s" in captured.out
    assert "Final:    None" in captured.out
    assert "Quality:  -5" in captured.out
    assert "Quality Feedback" not in captured.out

def test_print_stages_edge_cases(capsys):
    # 空リストの場合のテスト
    check_pipeline_status._print_stages([])
    captured = capsys.readouterr()
    assert captured.out == ""

    # status や index, name が全くない要素のテスト
    check_pipeline_status._print_stages([{}])
    captured = capsys.readouterr()
    assert "? [?] ?: ? " in captured.out

def test_generate_thumbnail_text_edge_cases():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_edge.png"
        # 空文字列のテキストの場合のテスト
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path, text="")
        assert res_path == out_path
        assert out_path.exists()

        # 非常に長いテキストの場合のテスト
        long_text = "A" * 1000
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path, text=long_text)
        assert res_path == out_path
        assert out_path.exists()


def test_fetch_pipeline_status_data_empty_response(capsys):
    # エッジケース: 空のレスポンスが返ってきた場合
    mock_response = MagicMock()
    mock_response.read.return_value = b""
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.fetch_pipeline_status_data()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Invalid JSON response from server" in captured.err

def test_print_stages_invalid_elements(capsys):
    # エッジケース: リスト内の要素が辞書ではない場合
    with pytest.raises(AttributeError):
        check_pipeline_status._print_stages([None])
    with pytest.raises(AttributeError):
        check_pipeline_status._print_stages(["not a dict"])

def test_print_result_none_values(capsys):
    # エッジケース: duration_seconds や quality_score が None の場合
    # duration_seconds が None の場合、TypeError が発生することを確認
    with pytest.raises(TypeError):
        check_pipeline_status._print_result({
            "duration_seconds": None,
            "final_path": "path",
            "quality_score": 100
        })

    # quality_score が None の場合、フォーマット自体は問題ない
    # ただし stage_results の要素が辞書でなく None の場合、AttributeError が発生することを確認
    with pytest.raises(AttributeError):
        check_pipeline_status._print_result({
            "duration_seconds": 10.0,
            "final_path": "path",
            "quality_score": None,
            "stage_results": [None]
        })

def test_generate_thumbnail_none_dimensions():
    # エッジケース: width や height が None の場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_none.png"
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=None)
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, height=None)

def test_generate_thumbnail_invalid_string_float_dimensions():
    # エッジケース: width や height が "1280.5" (floatを表す文字列) の場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_float.png"
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width="1280.5")

def test_validate_thumbnail_boundary_size():
    # エッジケース: ファイルサイズがちょうど 4MB 制限の境界値の場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "boundary.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch.object(Path, "stat") as mock_stat:
            # 4MB = 4 * 1024 * 1024 = 4194304 bytes
            # 4194304 はエラーになるはず
            mock_stat.return_value.st_size = 4 * 1024 * 1024
            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)
            
            # 4194303 (4MB - 1) は成功するはず
            mock_stat.return_value.st_size = 4 * 1024 * 1024 - 1
            meta = check_pipeline_status.validate_pipeline_status_thumbnail(out_path)
            assert meta["size_bytes"] == 4 * 1024 * 1024 - 1

def test_validate_thumbnail_is_directory():
    # エッジケース: 指定したパスがディレクトリの場合
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError):
            # ディレクトリの verify または load で例外を発生させる
            check_pipeline_status.validate_pipeline_status_thumbnail(tmpdir)

def test_validate_thumbnail_invalid_format_file():
    # エッジケース: 指定したファイルが画像形式ではないテキストファイルの場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "dummy.png"
        out_path.write_text("this is plain text, not a png image", encoding="utf-8")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_http_error():
    # エッジケース: urlopen が HTTPError を投げた場合
    import urllib.error
    fp = MagicMock()
    # HTTPError(url, code, msg, hdrs, fp)
    mock_http_error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/api/pipeline/status", 500, "Internal Server Error", {}, fp
    )
    with patch("urllib.request.urlopen", side_effect=mock_http_error):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_httperror"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()


def test_fetch_pipeline_status_data_invalid_encoding(capsys):
    # エッジケース: UTF-8デコードできない不正なバイト列が返ってきた場合
    mock_response = MagicMock()
    mock_response.read.return_value = b'\xff\xfe\xfd\xfc'
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.fetch_pipeline_status_data()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error during parsing" in captured.err

def test_print_pipeline_status_non_dict_input():
    # エッジケース: data が辞書型ではなく整数やリストなどの不正な型の場合
    with pytest.raises(AttributeError):
        check_pipeline_status.print_pipeline_status(123)
    with pytest.raises(AttributeError):
        check_pipeline_status.print_pipeline_status(["status_list"])

def test_print_stages_non_list_input():
    # エッジケース: stages がリスト型ではなくイテレートできない型の場合
    with pytest.raises(TypeError):
        check_pipeline_status._print_stages(123)

def test_print_result_extreme_values(capsys):
    # エッジケース: duration_seconds や quality_score が極端に大きい値の場合
    check_pipeline_status._print_result({
        "duration_seconds": 1.23e10,
        "final_path": "/path/to/video.mp4",
        "quality_score": 999999,
        "stage_results": [
            {"name": "encode", "success": True, "duration": 4.5e8}
        ]
    })
    captured = capsys.readouterr()
    assert "Duration: 12300000000.0s" in captured.out
    assert "Quality:  999999" in captured.out
    assert "✅ encode: 450000000.0s" in captured.out

def test_generate_thumbnail_invalid_path_type():
    # エッジケース: output_path が Path や文字列以外の不正な型の場合
    with pytest.raises((TypeError, AttributeError)):
        check_pipeline_status.generate_pipeline_status_thumbnail(123)

def test_validate_thumbnail_invalid_path_type():
    # エッジケース: file_path が Path や文字列以外の不正な型の場合
    with pytest.raises((TypeError, AttributeError)):
        check_pipeline_status.validate_pipeline_status_thumbnail(123)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_empty_task_id():
    # エッジケース: task_id が空文字列の場合
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
            task_id = ""
            result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
            result = json.loads(result_json)
            assert Path(result["path"]).name == ".png"
            assert Path(result["path"]).exists()

def test_fetch_pipeline_status_data_http_error_handling(capsys):
    # エッジケース: HTTPError が発生した場合のハンドリング
    import urllib.error
    fp = MagicMock()
    mock_http_error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/api/pipeline/status", 500, "Internal Server Error", {}, fp
    )
    with patch("urllib.request.urlopen", side_effect=mock_http_error):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.fetch_pipeline_status_data()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Failed to connect to pipeline server" in captured.err

def test_print_stages_invalid_status_types(capsys):
    # エッジケース: status が辞書のキーにない非想定の値の場合
    check_pipeline_status._print_stages([
        {"index": 1, "name": "stage1", "status": 999}
    ])
    captured = capsys.readouterr()
    assert "? [1] stage1: 999" in captured.out

    # エッジケース: status がリストなど unhashable な型の場合
    with pytest.raises(TypeError):
        check_pipeline_status._print_stages([
            {"index": 2, "name": "stage2", "status": ["running"]}
        ])

def test_print_feedback_invalid_types():
    # エッジケース: feedback にリスト以外のイテレート不可能な型が渡された場合
    with pytest.raises(TypeError):
        check_pipeline_status._print_feedback(123)

def test_print_result_invalid_duration_type():
    # エッジケース: stage_results 内の duration がフォーマット不可能な型の場合
    with pytest.raises((TypeError, ValueError)):
        check_pipeline_status._print_result({
            "duration_seconds": 10.0,
            "final_path": "path",
            "quality_score": 100,
            "stage_results": [
                {"name": "encode", "success": True, "duration": "ten_seconds"}
            ]
        })

def test_validate_thumbnail_zero_height():
    # エッジケース: height が 0 で、解像度不足のエラーが発生する場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "zero_height.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (1280, 0)
            mock_open.return_value.__enter__.return_value = mock_img
            with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_directory_traversal():
    # エッジケース: task_id に ../ を含む場合の挙動
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
            task_id = "../traversal_task"
            result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
            result = json.loads(result_json)
            # 保存先パスが親ディレクトリ側になっていることを検証
            expected_path = Path(tmpdir) / f"{task_id}.png"
            assert Path(result["path"]).resolve() == expected_path.resolve()
            assert expected_path.exists()

def test_generate_thumbnail_boundary_dimensions():
    # エッジケース: width や height が最小値 1 の場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_min.png"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(
            out_path, width=1, height=1
        )
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1, 1)

    # エッジケース: 極端に大きなサイズを指定して MemoryError が発生した際のクリーンアップ
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_huge.png"
        with patch("PIL.Image.new", side_effect=MemoryError("Out of memory")):
            with pytest.raises(MemoryError):
                check_pipeline_status.generate_pipeline_status_thumbnail(
                    out_path, width=100000, height=100000
                )
            # 一時ファイルが残っていないことを確認
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0

def test_generate_thumbnail_permission_error():
    # エッジケース: 保存先親ディレクトリの作成や書き込みで PermissionError が発生した場合のクリーンアップ
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_perm.png"
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        
        # 保存時 (Image.save) で PermissionError が発生した場合
        with patch("PIL.Image.Image.save", side_effect=PermissionError("Save permission denied")):
            with pytest.raises(PermissionError):
                check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
            # 一時ファイルが残っていないことを確認
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0


def test_validate_thumbnail_zero_byte_file():
    # エッジケース: 0バイトのファイルの場合、画像の破損検証で ValueError が発生することを確認
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "zero_byte.png"
        out_path.touch() # 0バイトファイルを作成
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            check_pipeline_status.validate_pipeline_status_thumbnail(out_path)


def test_print_result_stage_results_invalid_element_type():
    # エッジケース: stage_results の要素が辞書型ではない場合、AttributeError が発生することを確認
    with pytest.raises(AttributeError):
        check_pipeline_status._print_result({
            "duration_seconds": 10.0,
            "final_path": "path",
            "quality_score": 100,
            "stage_results": ["not a dict"]
        })


def test_print_stages_index_unusual_types(capsys):
    # エッジケース: index や name や detail に通常ではない型（リストや辞書など）が渡された場合でも適切にフォーマットされること
    check_pipeline_status._print_stages([
        {
            "index": [1, 2],
            "name": {"key": "val"},
            "status": "completed",
            "detail": None
        }
    ])
    captured = capsys.readouterr()
    assert "✅ [[1, 2]] {'key': 'val'}: completed None" in captured.out


def test_generate_thumbnail_multiline_and_unicode_text():
    # エッジケース: 改行や日本語、絵文字などを含むテキストを描画した場合のテスト
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_unicode.png"
        unicode_text = "日本語テスト\nLine 2: 🚀 Video Automation Pipeline 🌟\nLine 3"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path, text=unicode_text)
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1280, 720)


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_huge_task_id():
    # エッジケース: task_id が極端に長く、OSのパス名制限などで OSError が発生する場合の検証
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
            huge_task_id = "a" * 10000
            with pytest.raises(OSError):
                await check_pipeline_status.resolve_pipeline_status_thumbnail_task(huge_task_id)


def test_fetch_pipeline_status_data_returning_null(capsys):
    # エッジケース: APIが "null" を返した場合 (json.loads は None を返す)
    mock_response = MagicMock()
    mock_response.read.return_value = b"null"
    with patch("urllib.request.urlopen", return_value=mock_response):
        data = check_pipeline_status.fetch_pipeline_status_data()
        assert data is None

    # None を print_pipeline_status に渡すと AttributeError が発生することを確認
    with pytest.raises(AttributeError):
        check_pipeline_status.print_pipeline_status(data)


def test_generate_thumbnail_unusual_numeric_strings():
    # エッジケース: width/height に前後に余白がある文字列や、変換不可能な指数表記などの文字列を指定した場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_unusual.png"
        
        # 前後余白のある文字列 (int() で変換可能)
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(
            out_path, width="  1280  ", height="  720  "
        )
        assert res_path == out_path
        assert out_path.exists()
        
        # 指数表記文字列 (int() で直接変換できず ValueError になる)
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width="1.28e3")
            
        # 16進数表記文字列 (ValueError になる)
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width="0x500")


def test_print_stages_circular_reference(capsys):
    # エッジケース: 循環参照オブジェクトが stages の各項目に含まれている場合
    stage = {}
    stage['index'] = 1
    stage['name'] = 'circular_stage'
    stage['status'] = 'completed'
    stage['detail'] = stage
    
    # printした際に RecursionError にならずに安全に出力できることを確認
    check_pipeline_status._print_stages([stage])
    captured = capsys.readouterr()
    assert "✅ [1] circular_stage: completed" in captured.out


# --- 追加のエッジケーステスト ---

def test_print_pipeline_status_empty_dict(capsys):
    # エッジケース: 空辞書を渡した場合でも例外が発生せず、適切に出力されること
    check_pipeline_status.print_pipeline_status({})
    captured = capsys.readouterr()
    assert "Status:  None" in captured.out
    assert "Stage:   None" in captured.out

def test_print_result_missing_stage_results_keys(capsys):
    # エッジケース: stage_results の要素に必要なキー（name, success, duration）が欠落している場合
    result_data = {
        "duration_seconds": 10.0,
        "final_path": "path",
        "quality_score": 100,
        "stage_results": [
            {}  # 空の辞書
        ],
        "quality_feedback": ["Looks good"]
    }
    check_pipeline_status._print_result(result_data)
    captured = capsys.readouterr()
    assert "Duration: 10.0s" in captured.out
    assert "❌ None: 0.0s" in captured.out  # successがないため❌、nameがないためNone、durationがないため0.0s

def test_print_stages_missing_keys(capsys):
    # エッジケース: stages 内の辞書に必要なキーが欠落している場合
    stages = [
        {}  # 空辞書
    ]
    check_pipeline_status._print_stages(stages)
    captured = capsys.readouterr()
    # status がないため icon は ?、idx は ?、name は ?、detail は空文字列
    assert "? [?] ?: ? " in captured.out

def test_generate_thumbnail_extreme_boundary_dimensions():
    # エッジケース: 極端に小さな寸法 (1x1) でのサムネイル生成テスト
    import tempfile
    from pathlib import Path
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_1x1.png"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=1, height=1)
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1, 1)

def test_generate_thumbnail_invalid_type_dimensions():
    # エッジケース: width や height に int に変換不可能な不正な型が渡された場合
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_invalid_type.png"
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=[1280], height=720)
        with pytest.raises(ValueError, match="Width and height must be integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path, width=1280, height={"val": 720})

def test_validate_thumbnail_boundary_aspect_ratio():
    # エッジケース: アスペクト比が許容値 0.01 の境界線上付近のテスト
    import tempfile
    from pathlib import Path
    from PIL import Image
    
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_boundary.png"
        
        # 16:9 ちょうど -> 成功するはず
        img = Image.new("RGB", (1280, 720), color=(0, 0, 0))
        img.save(out_path, "PNG")
        res = check_pipeline_status.validate_pipeline_status_thumbnail(out_path)
        assert res["width"] == 1280
        
        # 誤差がちょうど 0.009 の場合 -> 成功するはず
        img_ok = Image.new("RGB", (1787, 1000), color=(0, 0, 0))
        img_ok.save(out_path, "PNG")
        res = check_pipeline_status.validate_pipeline_status_thumbnail(out_path)
        assert res["width"] == 1787

        # 誤差が 0.011 の場合 -> 失敗するはず (ValueError)
        img_fail = Image.new("RGB", (1789, 1000), color=(0, 0, 0))
        img_fail.save(out_path, "PNG")
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            check_pipeline_status.validate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_null_byte_path():
    # エッジケース: ヌル文字を含む無効なパスを指定した場合、例外が発生することを確認
    with pytest.raises((ValueError, TypeError, OSError)):
        check_pipeline_status.validate_pipeline_status_thumbnail("invalid\x00file.png")

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_special_char_task_id():
    # エッジケース: task_id にパスとして問題を起こしうる特殊文字が含まれる場合
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        # 2026-07-26: 以前は task_id に <>:"|?* を入れて OSError を期待していたが、
        # これらは Windows でのみ無効な文字で、Linux では正当なファイル名になる。
        # そのため CI(Linux) では例外が起きず DID NOT RAISE で失敗していた。
        # 出力先を「通常ファイルの配下」にすれば、どの OS でも書き込みに失敗する。
        blocker = Path(tmpdir) / "not_a_directory"
        blocker.write_text("x", encoding="utf-8")
        with patch("backend.check_pipeline_status.OUTPUT_DIR", str(blocker / "out")):
            with pytest.raises(OSError):
                await check_pipeline_status.resolve_pipeline_status_thumbnail_task("task_edge")

def test_generate_thumbnail_rename_exception_cleanup():
    # エッジケース: rename 時に例外が発生した場合、一時ファイルがクリーンアップされること
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_rename_fail.png"
        
        import pathlib
        concrete_class = pathlib.WindowsPath if os.name == "nt" else pathlib.PosixPath
        
        # rename で例外をスローさせる
        with patch.object(concrete_class, "rename", side_effect=OSError("Mocked rename failure")):
            with pytest.raises(OSError, match="Mocked rename failure"):
                check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
            
            # 一時ファイル (*.tmp) が残っていないことを確認
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            assert len(tmp_files) == 0
            assert not out_path.exists()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_json_decode_error():
    # エッジケース: APIレスポンスが不正なJSONでデコードエラーが発生した場合、安全にフォールバックすること
    mock_response = MagicMock()
    mock_response.read.return_value = b"{"  # 不正なJSON
    
    with patch("urllib.request.urlopen", return_value=mock_response):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_json_error"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()

def test_print_stages_none_input():
    # エッジケース: stages が None の場合に TypeError が発生することを確認
    with pytest.raises(TypeError):
        check_pipeline_status._print_stages(None)

def test_print_feedback_none(capsys):
    # エッジケース: feedback が None の場合に例外が発生せず何も出力されないこと
    check_pipeline_status._print_feedback(None)
    captured = capsys.readouterr()
    assert captured.out == ""


def test_fetch_pipeline_status_data_read_exception(capsys):
    # エッジケース: response.read() が例外を発生させた場合
    mock_response = MagicMock()
    mock_response.read.side_effect = OSError("Read timeout or connection reset")
    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(SystemExit) as excinfo:
            check_pipeline_status.fetch_pipeline_status_data()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error during connection" in captured.err

def test_fetch_pipeline_status_data_unexpected_connection_exception():
    # エッジケース: urlopen が極端な例外（KeyboardInterrupt）を投げた場合
    with patch("urllib.request.urlopen", side_effect=KeyboardInterrupt("Interrupted")):
        with pytest.raises(KeyboardInterrupt):
            check_pipeline_status.fetch_pipeline_status_data()

def test_print_stages_non_hashable_status_key():
    # エッジケース: statusの値が辞書など unhashable な型の場合の例外を検証
    with pytest.raises(TypeError):
        check_pipeline_status._print_stages([
            {"index": 2, "name": "stage2", "status": {"running": True}}
        ])

def test_print_result_extreme_float_values(capsys):
    # エッジケース: duration_seconds が inf や nan の場合
    check_pipeline_status._print_result({
        "duration_seconds": float('inf'),
        "final_path": "path",
        "quality_score": float('nan'),
        "stage_results": [
            {"name": "encode", "success": True, "duration": float('inf')}
        ],
        "quality_feedback": [123, None, {}]
    })
    captured = capsys.readouterr()
    assert "Duration: infs" in captured.out
    assert "Quality:  nan" in captured.out
    assert "✅ encode: infs" in captured.out
    assert "Quality Feedback:" in captured.out
    assert "  - 123" in captured.out
    assert "  - None" in captured.out

def test_generate_thumbnail_boolean_dimensions():
    # エッジケース: width や height に Boolean (True/False) を指定した場合
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_bool.png"
        res_path = check_pipeline_status.generate_pipeline_status_thumbnail(
            out_path, width=True, height=True
        )
        assert res_path == out_path
        assert out_path.exists()
        with Image.open(out_path) as img:
            assert img.size == (1, 1)

        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            check_pipeline_status.generate_pipeline_status_thumbnail(
                out_path, width=False, height=True
            )

def test_generate_thumbnail_mkdir_file_exists_error():
    # エッジケース: 保存先親ディレクトリが既にファイルとして存在する場合
    with tempfile.TemporaryDirectory() as tmpdir:
        parent_file = Path(tmpdir) / "blocked_dir"
        parent_file.touch()
        out_path = parent_file / "thumb.png"
        with pytest.raises((FileExistsError, OSError)):
            check_pipeline_status.generate_pipeline_status_thumbnail(out_path)

def test_validate_thumbnail_nan_aspect_ratio():
    # エッジケース: 画像サイズが 0x0 でアスペクト比計算の前に解像度チェックで ValueError が発生するケースを検証
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "thumb_nan.png"
        check_pipeline_status.generate_pipeline_status_thumbnail(out_path)
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (0, 0)
            mock_open.return_value.__enter__.return_value = mock_img
            with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
                check_pipeline_status.validate_pipeline_status_thumbnail(out_path)


@pytest.mark.asyncio
async def test_resolve_thumbnail_task_timeout_exception():
    # エッジケース: urlopen が TimeoutError などの特殊な接続エラーを投げた場合の非同期タスク挙動を検証
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("backend.check_pipeline_status.OUTPUT_DIR", tmpdir):
                task_id = "test_task_timeout"
                result_json = await check_pipeline_status.resolve_pipeline_status_thumbnail_task(task_id)
                result = json.loads(result_json)
                
                assert result["width"] == 1280
                assert result["height"] == 720
                assert Path(result["path"]).name == f"{task_id}.png"
                assert Path(result["path"]).exists()


