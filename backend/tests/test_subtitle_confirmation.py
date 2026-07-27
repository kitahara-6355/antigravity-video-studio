import pytest
import json
import logging
import sys
import importlib
import pydantic.root_model
import mcp.types
import google.genai
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

from backend.subtitle_confirmation import (
    ConfirmationItem,
    SubtitleConfirmationChecker,
    ConfirmationReportGenerator,
    analyze_scene_subtitles
)

# 1. model_registry のインポートエラーと正常系の再読込テスト
def test_model_registry_import_error_and_normal():
    import backend.subtitle_confirmation as sub_conf
    import builtins
    
    orig_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == "model_registry":
            raise ImportError("Mocked import error")
        return orig_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        importlib.reload(sub_conf)
        # デフォルト関数が "gemini-2.5-flash" を返すことを確認
        assert sub_conf.get_model("ai_confirmation") == "gemini-2.5-flash"
    importlib.reload(sub_conf)


# 2. ConfirmationItem のテスト
def test_confirmation_item():
    item = ConfirmationItem(
        id="test_001",
        timestamp="00:01:00",
        original_text="テストテキスト",
        concern="テスト懸念",
        category="uncertain",
        suggestion="提案テキスト"
    )
    assert item.id == "test_001"
    assert item.status == "pending"
    assert item.suggestion == "提案テキスト"
    assert item.modified_text is None


# 3. SubtitleConfirmationChecker._get_client のテスト
@pytest.mark.asyncio
async def test_get_client_success():
    checker = SubtitleConfirmationChecker()
    mock_client = MagicMock()
    
    # google.genai と gemini_client_factory を sys.modules でモックする
    mock_genai = MagicMock()
    mock_factory = MagicMock()
    mock_factory.get_gemini_client.return_value = mock_client
    
    modules_dict = {
        "google": mock_genai,
        "google.genai": mock_genai,
        "gemini_client_factory": mock_factory
    }
    
    with patch.dict("sys.modules", modules_dict):
        client = await checker._get_client()
        assert client == mock_client
        assert checker._client == mock_client
        
        # 二回目はキャッシュされたクライアントが返ることを確認 (86行目の _client is not None パス)
        client_cached = await checker._get_client()
        assert client_cached == mock_client


@pytest.mark.asyncio
async def test_get_client_failure():
    checker = SubtitleConfirmationChecker()
    
    # インポート時に例外を投げるように sys.modules を操作
    # もしくは google.genai などのモックが例外を発生させるようにする
    with patch.dict("sys.modules", {"gemini_client_factory": None}):
        with pytest.raises(Exception):
            await checker._get_client()


# 4. SubtitleConfirmationChecker.analyze_subtitle のテスト
@pytest.mark.asyncio
async def test_analyze_subtitle_success(tmp_path):
    # テスト用SRTファイルの作成
    srt_file = tmp_path / "scene_01.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nこんにちは、AIです。\n", encoding="utf-8")
    
    checker = SubtitleConfirmationChecker()
    
    # client のモック
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.text = '```json\n[{"timestamp": "00:00:02", "original_text": "こんにちは", "concern": "固有名詞", "category": "proper_noun", "suggestion": "ハロー"}]\n```'
    mock_client.aio.models.generate_content.return_value = mock_response
    
    # _get_client をモック
    with patch.object(checker, "_get_client", return_value=mock_client):
        items = await checker.analyze_subtitle(srt_file)
        
        assert len(items) == 1
        assert items[0].id == "scene_01_001"
        assert items[0].original_text == "こんにちは"
        assert items[0].concern == "固有名詞"
        assert items[0].category == "proper_noun"
        assert items[0].suggestion == "ハロー"


@pytest.mark.asyncio
async def test_analyze_subtitle_failure(tmp_path):
    srt_file = tmp_path / "scene_01.srt"
    srt_file.write_text("1\n00:00:01,000\n", encoding="utf-8")
    
    checker = SubtitleConfirmationChecker()
    
    mock_client = AsyncMock()
    mock_client.aio.models.generate_content.side_effect = Exception("API error")
    
    with patch.object(checker, "_get_client", return_value=mock_client):
        items = await checker.analyze_subtitle(srt_file)
        assert items == []


# 5. _parse_response のテスト
def test_parse_response_formats():
    checker = SubtitleConfirmationChecker()
    
    # ```json 形式
    resp_markdown = 'テキスト ```json\n[{"timestamp": "00:01:00", "original_text": "テスト", "concern": "懸念", "category": "uncertain", "suggestion": "提案"}]\n``` テキスト'
    items = checker._parse_response(resp_markdown, "prefix")
    assert len(items) == 1
    assert items[0].id == "prefix_001"
    assert items[0].original_text == "テスト"
    
    # 生JSON 形式 ( [ と ] のみ)
    resp_raw = '[{"timestamp": "00:02:00", "original_text": "生テスト", "concern": "懸念2", "category": "context", "suggestion": null}]'
    items = checker._parse_response(resp_raw, "prefix")
    assert len(items) == 1
    assert items[0].original_text == "生テスト"
    assert items[0].category == "context"
    
    # JSONが見つからない形式
    resp_none = '普通のテキストのみでJSONなし'
    items = checker._parse_response(resp_none, "prefix")
    assert items == []
    
    # 不正なJSON (JSONDecodeErrorのパス)
    resp_invalid = '```json\n[{"timestamp": "00:01:00", "original_text": "不完全なJSON"\n```'
    items = checker._parse_response(resp_invalid, "prefix")
    assert items == []


# 6. ConfirmationReportGenerator のテスト
def test_report_generator():
    generator = ConfirmationReportGenerator()
    
    # 空のアイテムリスト
    report_empty = generator.generate("シーン1", [])
    assert "✅ 確認が必要な箇所はありません。" in report_empty
    
    # アイテムあり
    items = [
        ConfirmationItem(
            id="scene1_001",
            timestamp="00:01:23",
            original_text="テストテキスト長い長い長い長い長い長い長い長い長い長い長い長い",
            concern="懸念理由",
            category="typo",
            suggestion="提案"
        )
    ]
    report_with_items = generator.generate("シーン1", items)
    assert "| scene1_001 | 00:01:23 |" in report_with_items
    assert "テストテキスト長い長い長い長い長い長い長い長い長い長い" in report_with_items # 30文字制限
    assert "懸念理由" in report_with_items
    
    # スクリーンショットあり
    report_with_screenshot = generator.generate("シーン1", items, screenshot_path="/path/to/screenshot.png")
    assert "![プレビュー](/path/to/screenshot.png)" in report_with_screenshot
    
    # フルレポート生成
    scenes = [
        {"name": "シーン1", "items": items, "screenshot": "/path/to/screenshot1.png"},
        {"name": "シーン2", "items": [], "screenshot": None}
    ]
    full_report = generator.generate_full_report("全体テストタイトル", scenes)
    assert "# 全体テストタイトル" in full_report
    assert "### シーン1" in full_report
    assert "### シーン2" in full_report
    assert "✅ 確認が必要な箇所はありません。" in full_report
    assert "操作方法" in full_report


# 7. analyze_scene_subtitles のテスト
@pytest.mark.asyncio
async def test_analyze_scene_subtitles_fn(tmp_path):
    srt_file1 = tmp_path / "scene_A.srt"
    srt_file1.write_text("1\n00:01:00\n", encoding="utf-8")
    srt_file2 = tmp_path / "scene_B.srt" # 存在しないパスにする
    
    # Checker の analyze_subtitle をモック化
    mock_items = [ConfirmationItem(id="A_001", timestamp="00:01:00", original_text="A", concern="C", category="typo")]
    
    with patch("backend.subtitle_confirmation.SubtitleConfirmationChecker.analyze_subtitle", return_value=mock_items) as mock_analyze:
        results = await analyze_scene_subtitles([srt_file1, srt_file2])
        
        # 存在するファイルだけが処理される
        mock_analyze.assert_called_once_with(srt_file1)
        assert "scene_A" in results
        assert "scene_B" not in results
        assert results["scene_A"] == mock_items


# 8. ConfirmationItem のデフォルト値およびシリアライズのテスト
def test_confirmation_item_defaults_and_serialization():
    from dataclasses import asdict
    item = ConfirmationItem(
        id="test_002",
        timestamp="00:02:00",
        original_text="テストテキスト2",
        concern="テスト懸念2",
        category="proper_noun"
    )
    assert item.suggestion is None
    assert item.status == "pending"
    assert item.modified_text is None
    
    # シリアライズの検証
    serialized = asdict(item)
    assert serialized["id"] == "test_002"
    assert serialized["suggestion"] is None
    assert serialized["status"] == "pending"
    assert serialized["modified_text"] is None


# 9. _parse_response のオプショナルキー欠損テスト
def test_parse_response_missing_optional_keys():
    checker = SubtitleConfirmationChecker()
    # timestamp, original_text, concern のみが存在し、suggestion や category が欠損している場合
    resp_missing = '```json\n[{"timestamp": "00:03:00", "original_text": "オプショナルキー欠損", "concern": "テスト懸念3"}]\n```'
    items = checker._parse_response(resp_missing, "prefix")
    assert len(items) == 1
    assert items[0].id == "prefix_001"
    assert items[0].timestamp == "00:03:00"
    assert items[0].original_text == "オプショナルキー欠損"
    assert items[0].concern == "テスト懸念3"
    assert items[0].category == "uncertain"  # デフォルト値
    assert items[0].suggestion is None  # デフォルト値


# 10. _get_client の ImportError 例外発生テスト
@pytest.mark.asyncio
async def test_get_client_import_error_path():
    checker = SubtitleConfirmationChecker()
    # patch.dict を使用して sys.modules の特定モジュールを None にし、インポートエラーを発生させる
    with patch.dict("sys.modules", {"google": None, "google.genai": None}):
        with pytest.raises(Exception):
            await checker._get_client()
