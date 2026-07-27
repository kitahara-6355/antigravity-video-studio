# -*- coding: utf-8 -*-
import sys
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import patch, MagicMock

# backend ディレクトリをパスに追加
backend_dir = Path("C:/Users/PC_User/.gemini/antigravity/brain/819c8bbd-e916-476d-b8a1-8582dedb4659/.system_generated/worktrees/subagent-test-weaver-Agent-001-self-b55fc33e/backend")
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import subtitle_confirmation


def test_subtitle_confirmation_thumbnail_existing_output(tmp_path):
    """正常系: すでに画像ファイルが存在する場合に、上書きして削除と作成がされること"""
    output_file = tmp_path / "existing_sub.png"
    output_file.write_text("existing dummy content")
    
    # 実行
    res_path = subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
        output_file, width=1280, height=720, text="Overwritten"
    )
    assert res_path.exists()
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_generation_exception(tmp_path):
    """異常系: 保存に失敗したときに一時ファイルが削除され、例外が再スローされること"""
    output_file = tmp_path / "sub_test_error.png"
    with patch("PIL.Image.Image.save", side_effect=Exception("Save Error")):
        with pytest.raises(Exception, match="Save Error"):
            subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
                output_file, width=1280, height=720
            )


def test_thumbnail_generation_exception_unlink_failure(tmp_path):
    """異常系: 保存に失敗し、さらに一時ファイル削除にも失敗した場合に、元の例外が再スローされること"""
    output_file = tmp_path / "sub_test_error2.png"
    
    # saveメソッドで実際に一時ファイルを生成してから例外を投げる
    def mock_save(self_img, path, format_type=None, **kwargs):
        Path(path).write_text("dummy temp file")
        raise Exception("Save Error")
        
    with patch("PIL.Image.Image.save", new=mock_save):
        with patch("pathlib.Path.unlink", side_effect=Exception("Unlink Error")):
            with pytest.raises(Exception, match="Save Error"):
                subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
                    output_file, width=1280, height=720
                )


def test_validate_thumbnail_quality_verify_exception(tmp_path):
    """異常系: 画像でないファイルを読み込ませ、verify()で例外が発生すること"""
    dummy_file = tmp_path / "not_an_image.png"
    dummy_file.write_text("This is plain text and not a png image.")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        subtitle_confirmation.validate_thumbnail_quality(dummy_file)


def test_validate_thumbnail_quality_load_exception(tmp_path):
    """異常系: 画像のオープンは成功するが、ピクセルデータ読み込み(load)で例外が発生すること"""
    output_file = tmp_path / "load_fail.png"
    subtitle_confirmation.generate_subtitle_confirmation_thumbnail(output_file, width=1280, height=720)
    
    with patch("PIL.Image.Image.load", side_effect=Exception("Load error")):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format: Load error"):
            subtitle_confirmation.validate_thumbnail_quality(output_file)


def test_parse_response_dict_fallback():
    """正常系: レスポンスがリストではなく単一の辞書だった場合、自動的に要素1のリストにフォールバックすること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    resp_dict = '```json\n{"timestamp": "00:04:00", "original_text": "辞書フォールバック", "concern": "単一辞書テスト"}\n```'
    items = checker._parse_response(resp_dict, "prefix")
    assert len(items) == 1
    assert items[0].original_text == "辞書フォールバック"
    assert items[0].id == "prefix_001"


def test_parse_response_non_dict_items():
    """正常系: リスト内に辞書ではない不正な型が含まれる場合、それをスキップすること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    resp_mixed = '```json\n[{"timestamp": "00:05:00", "original_text": "正常", "concern": "正常"}, "invalid_string_item", 12345]\n```'
    items = checker._parse_response(resp_mixed, "prefix")
    assert len(items) == 1
    assert items[0].original_text == "正常"


def test_parse_response_invalid_data_type():
    """異常系: パースされた結果がリストでも辞書でもない場合、空のリストを返すこと"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    resp_invalid = '```json\n"just a string, not list or dict"\n```'
    items = checker._parse_response(resp_invalid, "prefix")
    assert items == []


def test_parse_response_unexpected_exception():
    """異常系: 予期しない例外が発生した場合に、例外が再スローされること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    # json.loads をパッチして任意の例外を発生させる
    with patch("json.loads", side_effect=RuntimeError("Unexpected parse failure")):
        with pytest.raises(RuntimeError, match="Unexpected parse failure"):
            checker._parse_response('```json\n[{"timestamp": "00:01:00"}]\n```', "prefix")


def test_parse_response_unclosed_markdown():
    """正常系: ```json の後に閉じ ``` がない場合でも、最後まで抽出してパースできること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    resp_unclosed = '```json\n[{"timestamp": "00:06:00", "original_text": "閉じなし", "concern": "テスト"}]'
    items = checker._parse_response(resp_unclosed, "prefix")
    assert len(items) == 1
    assert items[0].original_text == "閉じなし"


def test_parse_response_unclosed_bracket():
    """異常系: [ はあるが ] がない場合、空のリストを返すこと"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    resp_unclosed = '[{"timestamp": "00:07:00", "original_text": "括弧閉じなし"'
    items = checker._parse_response(resp_unclosed, "prefix")
    assert items == []


@pytest.mark.asyncio
async def test_get_client_module_not_found_specifically():
    """異常系: インポート時に ModuleNotFoundError が発生した場合に、適切にログ出力して再スローすること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    # google モジュールをインポートエラーにするために sys.modules を操作
    with patch.dict("sys.modules", {"google": None}):
        with pytest.raises(ModuleNotFoundError):
            await checker._get_client()


@pytest.mark.asyncio
async def test_get_client_unexpected_exception():
    """異常系: クライアント初期化時に予期せぬ例外が発生した場合、適切にログ出力して再スローすること"""
    checker = subtitle_confirmation.SubtitleConfirmationChecker()
    mock_genai = MagicMock()
    mock_factory = MagicMock()
    mock_factory.get_gemini_client.side_effect = RuntimeError("Connection Failed Mock")
    
    modules_dict = {
        "google": mock_genai,
        "google.genai": mock_genai,
        "gemini_client_factory": mock_factory
    }
    with patch.dict("sys.modules", modules_dict):
        with pytest.raises(RuntimeError, match="Connection Failed Mock"):
            await checker._get_client()


def test_thumbnail_generation_os_error_and_unlink_warning(tmp_path, caplog):
    """異常系: 保存時の OSError で、一時ファイルの削除時に OSError が発生した場合に警告ログを出力し再スローすること"""
    output_file = tmp_path / "os_error_test.png"
    
    def mock_save(self_img, path, format_type=None, **kwargs):
        Path(path).write_text("temp text")
        raise OSError("Disk Full Mock")
        
    with patch("PIL.Image.Image.save", new=mock_save):
        with patch("pathlib.Path.unlink", side_effect=OSError("Permission Denied Mock")):
            with caplog.at_level("WARNING"):
                with pytest.raises(OSError, match="Disk Full Mock"):
                    subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
                        output_file, width=1280, height=720
                    )
                assert any("Failed to remove temp file" in record.message for record in caplog.records)


def test_thumbnail_generation_unexpected_exception(tmp_path):
    """異常系: OSError 以外の予期せぬ例外（例：AttributeError）が発生した場合に再スローされること"""
    output_file = tmp_path / "attr_error.png"
    with patch("PIL.ImageDraw.Draw", side_effect=AttributeError("Unexpected Attribute Error")):
        with pytest.raises(AttributeError, match="Unexpected Attribute Error"):
            subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
                output_file, width=1280, height=720
            )
