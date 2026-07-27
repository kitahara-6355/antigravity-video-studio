import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# project root と backend をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ["GOOGLE_API_KEY"] = "dummy_key_for_stub_mode"

class DummyAPIError(Exception):
    def __init__(self, code, response_json, response=None):
        self.code = code
        self.response_json = response_json
        self.response = response
        super().__init__(f"API Error {code}")

import sys
from unittest.mock import MagicMock
_mock_errors = MagicMock()
_mock_errors.APIError = DummyAPIError
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.errors"] = _mock_errors

from backend.subtitle_normalizer import (
    NormalizedSegment,
    UncertainItem,
    SubtitleNormalizer,
    SRTExporter,
    normalize_subtitles,
    export_srt,
    subtitle_normalizer as global_normalizer,
    srt_exporter as global_exporter
)

def test_dataclass_initialization():
    """NormalizedSegment と UncertainItem が正しくインスタンス化できることを確認"""
    segment = NormalizedSegment(
        id="seg_001",
        start=1.23,
        end=4.56,
        original_text="テスト",
        normalized_text="テスト修正",
        corrections=[{"original": "テス", "corrected": "テスト"}],
        speaker="Speaker 1",
        confidence=0.9
    )
    assert segment.id == "seg_001"
    assert segment.start == 1.23
    assert segment.end == 4.56
    assert segment.original_text == "テスト"
    assert segment.normalized_text == "テスト修正"
    assert segment.corrections == [{"original": "テス", "corrected": "テスト"}]
    assert segment.speaker == "Speaker 1"
    assert segment.confidence == 0.9

    uncertain = UncertainItem(
        original="わからん",
        candidates=["候補1", "候補2"],
        context="前後文脈",
        segment_id="seg_001",
        confidence=0.5
    )
    assert uncertain.original == "わからん"
    assert uncertain.candidates == ["候補1", "候補2"]
    assert uncertain.context == "前後文脈"
    assert uncertain.segment_id == "seg_001"
    assert uncertain.confidence == 0.5


def test_subtitle_normalizer_init():
    """SubtitleNormalizer の初期化を検証"""
    mock_client = MagicMock()
    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model") as mock_get_model:
        normalizer = SubtitleNormalizer()
        assert normalizer.client == mock_client
        assert normalizer.model == "mock-model"
        mock_get_model.assert_called_once_with("subtitle_split")


def test_parse_response_success():
    """JSON形式のAIレスポンスが正しくパースされることを検証"""
    normalizer = SubtitleNormalizer.__new__(SubtitleNormalizer)
    text = """
    何らかのノイズテキスト
    ```json
    {
      "normalized_segments": [
        {"id": "seg_001", "text": "修正後テキスト"}
      ],
      "uncertain_items": [
        {"original": "認識テキスト", "candidates": ["候補1", "候補2"], "context": "前後文脈", "segment_id": "seg_001", "confidence": 0.6}
      ]
    }
    ```
    """
    result = normalizer._parse_response(text)
    assert "normalized_segments" in result
    assert len(result["normalized_segments"]) == 1
    assert result["normalized_segments"][0]["id"] == "seg_001"
    assert result["normalized_segments"][0]["text"] == "修正後テキスト"
    assert "uncertain_items" in result
    assert len(result["uncertain_items"]) == 1
    assert result["uncertain_items"][0]["original"] == "認識テキスト"


def test_parse_response_invalid():
    """JSONとしてパースできない、あるいはJSONが見つからない場合に ValueError を投げることを検証"""
    normalizer = SubtitleNormalizer.__new__(SubtitleNormalizer)
    # パースエラーになるような不正なJSON
    text_invalid = "{ invalid json }"
    with pytest.raises(ValueError):
        normalizer._parse_response(text_invalid)

    # JSONが含まれないテキスト
    text_no_json = "これはただのテキストでJSONはありません。"
    with pytest.raises(ValueError):
        normalizer._parse_response(text_no_json)


def test_normalize_success():
    """正常系: AI正規化と辞書適用が正しく動作することを検証"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    {
      "normalized_segments": [
        {"id": "seg_001", "text": "こんにちは"}
      ],
      "uncertain_items": []
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    # proper_noun_dict の get_all_entries をモック
    mock_dict_entries = [{"incorrect": "こんにちわ", "correct": "こんにちは", "type": "word"}]
    # apply_dictionary をモック
    mock_apply_dictionary = MagicMock(return_value=("こんにちは（修正）", [{"original": "こんにちは", "corrected": "こんにちは（修正）", "type": "word"}]))

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model"), \
         patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=mock_dict_entries), \
         patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "こんにちわ"}]
        result = normalizer.normalize(whisper_segments, apply_dict=True)

        assert result["stats"]["total_segments"] == 1
        assert result["stats"]["normalized_segments"] == 1
        assert result["stats"]["corrections_made"] == 1
        assert result["normalized_segments"][0]["text"] == "こんにちは（修正）"
        mock_apply_dictionary.assert_called()


def test_normalize_exception_propagates():
    """想定外の例外（RuntimeErrorなど）が発生した場合はフォールバックせず呼び出し元に伝播することを検証"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("Unexpected System Error")

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model"):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "想定外エラー"}]
        with pytest.raises(RuntimeError):
            normalizer.normalize(whisper_segments, apply_dict=True)


def test_normalize_api_error_fallback():
    """APIErrorが発生した際に適切にフォールバックされることを検証"""
    from google.genai.errors import APIError
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = APIError(code=500, response_json={})

    mock_apply_dictionary = MagicMock(side_effect=lambda text: (text, []))

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model"), \
         patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]), \
         patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "APIエラーフォールバック"}]
        result = normalizer.normalize(whisper_segments, apply_dict=True)

        assert result["stats"]["total_segments"] == 1
        assert result["normalized_segments"][0]["text"] == "APIエラーフォールバック"


def test_normalize_value_error_fallback():
    """ValueErrorが発生した際に適切にフォールバックされることを検証"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = ValueError("Invalid Arguments")

    mock_apply_dictionary = MagicMock(side_effect=lambda text: (text, []))

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model"), \
         patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]), \
         patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "引数エラーフォールバック"}]
        result = normalizer.normalize(whisper_segments, apply_dict=True)

        assert result["stats"]["total_segments"] == 1
        assert result["normalized_segments"][0]["text"] == "引数エラーフォールバック"


def test_normalize_client_none_fallback():
    """clientがNoneの場合に適切にフォールバックされることを検証"""
    mock_apply_dictionary = MagicMock(side_effect=lambda text: (text, []))

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=None), \
         patch("backend.subtitle_normalizer.get_model", return_value="mock-model"), \
         patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]), \
         patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "クライアントなしフォールバック"}]
        result = normalizer.normalize(whisper_segments, apply_dict=True)

        assert result["stats"]["total_segments"] == 1
        assert result["normalized_segments"][0]["text"] == "クライアントなしフォールバック"

def test_normalize_parse_error_fallback():
    """AIレスポンスのパースエラー時に適切にフォールバックされることを検証"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid json response"
    mock_client.models.generate_content.return_value = mock_response

    mock_apply_dictionary = MagicMock(side_effect=lambda text: (text, []))

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client),          patch("backend.subtitle_normalizer.get_model", return_value="mock-model"),          patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]),          patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "パースエラー時フォールバック"}]
        result = normalizer.normalize(whisper_segments, apply_dict=True)

        assert result["stats"]["total_segments"] == 1
        assert result["normalized_segments"][0]["text"] == "パースエラー時フォールバック"


def test_fallback_normalize_directly():
    """_fallback_normalize が直接正しく機能することを検証"""
    normalizer = SubtitleNormalizer.__new__(SubtitleNormalizer)

    mock_apply_dictionary = MagicMock(side_effect=lambda text: (text + "!", [{"original": text, "corrected": text + "!", "type": "word"}]))

    with patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):
        segments = [{"text": "テスト"}]
        res = normalizer._fallback_normalize(segments)
        assert len(res["normalized_segments"]) == 1
        assert res["normalized_segments"][0]["text"] == "テスト!"
        assert res["normalized_segments"][0]["original_text"] == "テスト"
        assert len(res["normalized_segments"][0]["corrections"]) == 1


def test_srt_exporter_format_timestamp():
    """秒から SRT タイムスタンプへの変換を検証"""
    assert SRTExporter.format_timestamp(0.0) == "00:00:00,000"
    assert SRTExporter.format_timestamp(65.5) == "00:01:05,500"
    assert SRTExporter.format_timestamp(3665.123) == "01:01:05,123"


def test_srt_exporter_export(tmp_path):
    """SRT ファイル出力の検証"""
    segments = [
        {"start": 1.2, "end": 3.4, "text": "こんにちは"},
        {"start": 4.5, "end": 6.7, "normalized_text": "さようなら"}
    ]
    output_file = tmp_path / "subdir" / "test.srt"

    res_path = SRTExporter.export(segments, output_file)
    assert res_path == output_file
    assert output_file.exists()

    content = output_file.read_text(encoding="utf-8")
    expected_lines = [
        "1",
        "00:00:01,200 --> 00:00:03,400",
        "こんにちは",
        "",
        "2",
        "00:00:04,500 --> 00:00:06,700",
        "さようなら",
        ""
    ]
    assert content == "\n".join(expected_lines)


def test_srt_exporter_export_vtt(tmp_path):
    """WebVTT ファイル出力の検証"""
    segments = [
        {"start": 1.2, "end": 3.4, "text": "こんにちは"},
    ]
    output_file = tmp_path / "test.vtt"

    res_path = SRTExporter.export_vtt(segments, output_file)
    assert res_path == output_file
    assert output_file.exists()

    content = output_file.read_text(encoding="utf-8")
    expected_lines = [
        "WEBVTT",
        "",
        "1",
        "00:00:01.200 --> 00:00:03.400",
        "こんにちは",
        ""
    ]
    assert content == "\n".join(expected_lines)


def test_global_functions(tmp_path):
    """グローバル関数の検証"""
    mock_segments = [{"id": "seg_001", "text": "テスト"}]
    mock_normalizer = MagicMock()
    mock_normalizer.normalize.return_value = {"normalized_segments": []}

    mock_exporter = MagicMock()
    mock_exporter.export.return_value = tmp_path / "test.srt"

    with patch("backend.subtitle_normalizer.subtitle_normalizer", mock_normalizer), \
         patch("backend.subtitle_normalizer.srt_exporter", mock_exporter):

        res_norm = normalize_subtitles(mock_segments)
        assert res_norm == {"normalized_segments": []}
        mock_normalizer.normalize.assert_called_once_with(mock_segments)

        res_exp = export_srt(mock_segments, tmp_path / "test.srt")
        assert res_exp == tmp_path / "test.srt"
        mock_exporter.export.assert_called_once_with(mock_segments, tmp_path / "test.srt")


def test_normalize_without_dictionary():
    """apply_dict=False の場合に辞書適用がスキップされることを検証"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    {
      "normalized_segments": [
        {"id": "seg_001", "text": "こんにちわ"}
      ],
      "uncertain_items": []
    }
    """
    mock_client.models.generate_content.return_value = mock_response

    # apply_dictionary をモックして呼び出されないことを確認する
    mock_apply_dictionary = MagicMock()

    with patch("backend.subtitle_normalizer.get_gemini_client", return_value=mock_client),          patch("backend.subtitle_normalizer.get_model", return_value="mock-model"),          patch("backend.subtitle_normalizer.proper_noun_dict.get_all_entries", return_value=[]),          patch("backend.subtitle_normalizer.apply_dictionary", mock_apply_dictionary):

        normalizer = SubtitleNormalizer()
        whisper_segments = [{"id": "seg_001", "text": "こんにちわ"}]
        result = normalizer.normalize(whisper_segments, apply_dict=False)

        assert result["stats"]["total_segments"] == 1
        assert result["stats"]["normalized_segments"] == 1
        assert result["stats"]["corrections_made"] == 0
        assert result["normalized_segments"][0]["text"] == "こんにちわ"
        mock_apply_dictionary.assert_not_called()


def test_srt_exporter_get_value_object():
    """SRTExporter._get_value がオブジェクトから正しく属性値を取得できることを検証"""
    segment = NormalizedSegment(
        id="seg_001",
        start=1.23,
        end=4.56,
        original_text="テスト",
        normalized_text="テスト修正",
        corrections=[]
    )
    # 存在する属性
    assert SRTExporter._get_value(segment, "start") == 1.23
    assert SRTExporter._get_value(segment, "end") == 4.56
    assert SRTExporter._get_value(segment, "normalized_text") == "テスト修正"
    # 存在しない属性（デフォルト値の検証）
    assert SRTExporter._get_value(segment, "non_existent", "default_val") == "default_val"






def test_export_with_none_timestamps(tmp_path):
    """start や end が明示的に None の場合でもクラッシュせずデフォルト値(0.0)にフォールバックされることを検証"""
    segments = [
        {"start": None, "end": 2.5, "text": "Noneスタート"},
        {"start": 3.0, "end": None, "text": "Noneエンド"}
    ]
    output_file = tmp_path / "test_none.srt"
    res_path = SRTExporter.export(segments, output_file)
    assert res_path == output_file
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,500" in content
    assert "00:00:03,000 --> 00:00:00,000" in content


def test_export_with_negative_timestamps(tmp_path):
    """start や end が負の数の場合にクラッシュせず 0.0 (00:00:00,000) にクリップされることを検証"""
    segments = [
        {"start": -1.5, "end": 2.5, "text": "負のスタート"}
    ]
    output_file = tmp_path / "test_neg.srt"
    res_path = SRTExporter.export(segments, output_file)
    assert res_path == output_file
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,500" in content