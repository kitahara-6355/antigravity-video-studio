import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import tempfile
import json
import os
import subprocess

from interactive_preview import (
    validate_timestamp,
    validate_path,
    SubtitleConfirmationChecker,
    ConfirmationItem,
    TelopSuggester,
    TelopSuggestion,
    TelopPreviewRenderer,
    run_full_pipeline,
)

# 1. validate_timestamp 不正形式
def test_validate_timestamp_invalid():
    with pytest.raises(ValueError):
        validate_timestamp("invalid_time")

# 2. validate_path 例外 & 許可ディレクトリ外 & 比較例外
def test_validate_path_errors(tmp_path):
    # A. 例外パターン (Pathオブジェクトにできない型を渡す)
    with pytest.raises(ValueError):
        validate_path([1, 2, 3])

    # B. 許可ディレクトリ外パターン
    with pytest.raises(ValueError):
        # 確実に許可されない絶対パスを構築
        outside_path = Path("C:/Users/PC_User/Totally/Fake/Directory/outside.mp4")
        validate_path(outside_path)

    # C. 比較処理での例外発生パターン (71-72行目の except Exception のカバー)
    with patch.object(Path, "resolve") as mock_resolve:
        mock_resolved_path = MagicMock()
        # resolved_path.parents プロパティのアクセス時に例外を発生させる
        type(mock_resolved_path).parents = property(lambda self: exec('raise(Exception("parents error"))'))
        mock_resolve.return_value = mock_resolved_path

        with pytest.raises(ValueError, match="Path is outside allowed directories"):
            validate_path(Path("C:/dummy_path"))

# 2.5. validate_path tempfile.gettempdir 例外フォールバック (56-57行目のカバー)
def test_validate_path_tempdir_fallback():
    with patch("tempfile.gettempdir", side_effect=Exception("tempfile error")):
        # gettempdir がエラーになっても、プロジェクトルート配下の有効なパスであれば検証をパスすることを確認
        project_root = Path(__file__).parent.parent.resolve()
        assert validate_path(project_root) == project_root

# 3. SubtitleConfirmationChecker analyze 正常系・通信エラー・例外系
@patch("gemini_client_factory.get_gemini_client")
@patch("model_registry.get_model")
def test_subtitle_confirmation_checker_analyze(mock_get_model, mock_get_client, tmp_path):
    checker = SubtitleConfirmationChecker()
    mock_get_model.return_value = "dummy-model"

    # A. 正常系 (JSON応答)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '```json\n[{"timestamp": "00:01:30", "original_text": "テスト", "concern": "懸念点", "category": "proper_noun", "suggestion": "修正案"}]\n```'
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    results = checker.analyze("字幕コンテンツ", "scene_test")
    assert len(results) == 1
    assert results[0].original_text == "テスト"

    # B. 通信エラー (ConnectionError -> TimeoutError -> 成功)
    mock_response_ok = MagicMock()
    mock_response_ok.text = '```json\n[{"timestamp": "00:02:00", "original_text": "成功", "concern": "OK", "category": "uncertain"}]\n```'
    mock_client_retry = MagicMock()
    mock_client_retry.models.generate_content.side_effect = [
        ConnectionError("connection failed"),
        TimeoutError("timeout"),
        mock_response_ok
    ]
    mock_get_client.return_value = mock_client_retry
    
    with patch("time.sleep") as mock_sleep:
        results = checker.analyze("字幕コンテンツ", "scene_test")
        assert len(results) == 1
        assert results[0].original_text == "成功"
        assert mock_sleep.call_count == 2

    # C. 通信エラー (3回すべて失敗)
    mock_client_fail = MagicMock()
    mock_client_fail.models.generate_content.side_effect = ConnectionError("always fail")
    mock_get_client.return_value = mock_client_fail
    with patch("time.sleep") as mock_sleep:
        results = checker.analyze("字幕コンテンツ", "scene_test")
        assert results == []

    # D. その他の例外 (リトライせず即 break)
    mock_client_ex = MagicMock()
    mock_client_ex.models.generate_content.side_effect = RuntimeError("unexpected crash")
    mock_get_client.return_value = mock_client_ex
    results = checker.analyze("字幕コンテンツ", "scene_test")
    assert results == []

# 4. SubtitleConfirmationChecker _parse_response パースエラー・キー不足・型エラー
def test_subtitle_confirmation_checker_parse_errors():
    checker = SubtitleConfirmationChecker()
    # A. JSONパースエラー
    assert checker._parse_response("[{invalid json", "prefix") == []

    # B. KeyError のカバー用
    bad_item_key = MagicMock()
    bad_item_key.get.side_effect = KeyError("missing key")
    with patch("json.loads", return_value=[bad_item_key]):
        assert checker._parse_response('```json\n[{"trigger_key_error": 1}]\n```', "prefix") == []

    # C. TypeError のカバー用
    bad_item_type = MagicMock()
    bad_item_type.get.side_effect = TypeError("type error")
    with patch("json.loads", return_value=[bad_item_type]):
        assert checker._parse_response('```json\n[{"trigger_type_error": 1}]\n```', "prefix") == []

    # D. JSON形式が見つからないケース
    assert checker._parse_response("Plain text without json brackets", "prefix") == []
    
    # E. 生JSON
    results = checker._parse_response('[{"timestamp": "00:00:10", "original_text": "raw", "concern": "c", "category": "c"}]', "prefix")
    assert len(results) == 1

# 5. TelopSuggester suggest 正常系・通信エラー・例外系
@patch("gemini_client_factory.get_gemini_client")
@patch("model_registry.get_model")
def test_telop_suggester_suggest(mock_get_model, mock_get_client):
    suggester = TelopSuggester()
    mock_get_model.return_value = "dummy-model"

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '```json\n[{"timestamp": "00:00:05", "duration": 3.0, "text": "テロップ", "reason": "理由", "position": "top"}]\n```'
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    results = suggester.suggest("対談字幕", "scene_test")
    assert len(results) == 1
    assert results[0].text == "テロップ"

    # 通信エラー
    mock_client_fail = MagicMock()
    mock_client_fail.models.generate_content.side_effect = TimeoutError("timeout")
    mock_get_client.return_value = mock_client_fail
    with patch("time.sleep"):
        assert suggester.suggest("対談字幕", "scene_test") == []

    # その他の例外 (272-274行目のカバー)
    mock_client_ex = MagicMock()
    mock_client_ex.models.generate_content.side_effect = RuntimeError("unexpected telop sug error")
    mock_get_client.return_value = mock_client_ex
    assert suggester.suggest("対談字幕", "scene_test") == []

# 6. TelopSuggester _parse_response 異常系
def test_telop_suggester_parse_errors():
    suggester = TelopSuggester()
    # キー不足 (durationが欠落してデフォルト3.0になることを確認)
    results = suggester._parse_response('```json\n[{"timestamp": "00:00:05", "text": "t", "reason": "r"}]\n```', "prefix")
    assert len(results) == 1
    assert results[0].duration == 3.0

    # KeyError のカバー用
    bad_item_key = MagicMock()
    bad_item_key.get.side_effect = KeyError("missing key")
    with patch("json.loads", return_value=[bad_item_key]):
        assert suggester._parse_response('```json\n[{"trigger_key_error": 1}]\n```', "prefix") == []

    # JSONが見つからない
    assert suggester._parse_response("no brackets", "prefix") == []

    # 型/値エラー (durationに数値変換できない文字列)
    results = suggester._parse_response('```json\n[{"timestamp": "00:00:05", "duration": "bad_float", "text": "t"}]\n```', "prefix")
    assert results == []

# 7. TelopPreviewRenderer バリデーションエラー
def test_telop_preview_renderer_validation_errors(tmp_path):
    renderer = TelopPreviewRenderer(tmp_path)
    telop_bad_pos = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0, text="t", reason="r", position="invalid_pos")
    
    # A. Invalid position
    with pytest.raises(ValueError, match="Invalid telop position"):
        renderer.render(tmp_path / "video.mp4", telop_bad_pos, "out")

    # B. Invalid output name
    telop_ok = TelopSuggestion(id="t2", timestamp="00:00:05", duration=3.0, text="t", reason="r", position="top")
    with pytest.raises(ValueError, match="Invalid output name"):
        renderer.render(tmp_path / "video.mp4", telop_ok, "dir/out.jpg")
        
    with pytest.raises(ValueError, match="Invalid output name"):
        renderer.render(tmp_path / "video.mp4", telop_ok, ".")

# 8. TelopPreviewRenderer FFmpeg実行例外
def test_telop_preview_renderer_ffmpeg_exceptions(tmp_path):
    renderer = TelopPreviewRenderer(tmp_path)
    telop = TelopSuggestion(id="t1", timestamp="00:00:05", duration=3.0, text="t", reason="r", position="top")
    
    # A. TimeoutExpired
    with patch("interactive_preview.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60.0)):
        result = renderer.render(tmp_path / "video.mp4", telop, "out_timeout")
        assert result is None

    # B. FileNotFoundError
    with patch("interactive_preview.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        result = renderer.render(tmp_path / "video.mp4", telop, "out_fnf")
        assert result is None

# 9. run_full_pipeline フル網羅
@patch("interactive_preview.SubtitleConfirmationChecker")
@patch("interactive_preview.TelopSuggester")
@patch("interactive_preview.TelopPreviewRenderer")
def test_run_full_pipeline_full_paths(mock_renderer_cls, mock_suggester_cls, mock_checker_cls, tmp_path):
    # 各インスタンスのモック設定
    mock_checker = MagicMock()
    mock_checker.analyze.return_value = [ConfirmationItem(id="c1", timestamp="00:00:01", original_text="t", concern="c", category="uncertain")]
    mock_checker_cls.return_value = mock_checker

    mock_suggester = MagicMock()
    mock_suggester.suggest.return_value = [
        TelopSuggestion(id="t1", timestamp="00:00:02", duration=3.0, text="telop1", reason="r"),
        TelopSuggestion(id="t2", timestamp="00:00:03", duration=3.0, text="telop2", reason="r")
    ]
    mock_suggester_cls.return_value = mock_suggester

    mock_renderer = MagicMock()
    mock_renderer.render.return_value = tmp_path / "preview1.jpg"
    mock_renderer_cls.return_value = mock_renderer

    # ビデオファイルを実際に作成する
    video_path = tmp_path / "video.mp4"
    video_path.write_text("fake video content", encoding="utf-8")

    # 字幕ファイルも実際に作成する
    srt_path = tmp_path / "subtitle.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:04,000\nテスト字幕", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    scenes = [{
        "scene_id": "scene_001",
        "name": "scene_full",
        "video": str(video_path),
        "subtitle": str(srt_path)
    }]

    # パイプライン実行
    run_full_pipeline(
        scenes=scenes,
        output_dir=output_dir
    )

    # config.json が作成されているか確認
    config_path = output_dir / "scene_001_config.json"
    assert config_path.exists()
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        assert len(config_data["telops"]) == 2
        assert len(config_data["confirmations"]) == 1

    # レンダラーが呼び出されたことを確認
    assert mock_renderer.render.call_count == 2
