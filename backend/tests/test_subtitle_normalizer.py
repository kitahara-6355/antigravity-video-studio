"""
test_subtitle_normalizer.py — subtitle_normalizer.py のユニットテスト
SRTExporter の全メソッド + SubtitleNormalizer の _parse_response, _fallback_normalize をカバー。
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# インポートチェーン依存をモック
_mock_pn = MagicMock()
_mock_pn.proper_noun_dict = MagicMock()
_mock_pn.proper_noun_dict.get_all_entries.return_value = []
_mock_pn.apply_dictionary = MagicMock(side_effect=lambda t: (t, []))

class DummyAPIError(Exception):
    def __init__(self, code, response_json, response=None):
        self.code = code
        self.response_json = response_json
        self.response = response
        super().__init__(f"API Error {code}")

_mock_errors = MagicMock()
_mock_errors.APIError = DummyAPIError

_mock_modules = {
    "dotenv": MagicMock(),
    "gemini_client_factory": MagicMock(get_gemini_client=MagicMock(return_value=MagicMock())),
    "model_registry": MagicMock(get_model=MagicMock(return_value="gemini-2.0-flash")),
    "proper_noun_dict": _mock_pn,
    "google": MagicMock(),
    "google.genai": MagicMock(),
    "google.genai.errors": _mock_errors,
}


@pytest.fixture(autouse=True)
def _mock_imports():
    with patch.dict(sys.modules, _mock_modules):
        if "subtitle_normalizer" in sys.modules:
            del sys.modules["subtitle_normalizer"]
        yield


def _import_module():
    import importlib
    if "subtitle_normalizer" in sys.modules:
        return importlib.reload(sys.modules["subtitle_normalizer"])
    return importlib.import_module("subtitle_normalizer")


class TestSRTExporter:
    """SRTExporter テスト"""

    def test_format_timestamp(self):
        mod = _import_module()
        assert mod.SRTExporter.format_timestamp(0.0) == "00:00:00,000"
        assert mod.SRTExporter.format_timestamp(3661.5) == "01:01:01,500"
        assert mod.SRTExporter.format_timestamp(59.999) == "00:00:59,999"

    def test_export_srt(self, tmp_path):
        mod = _import_module()
        segments = [
            {"start": 0.0, "end": 5.0, "text": "こんにちは"},
            {"start": 5.0, "end": 10.0, "text": "テストです"},
        ]
        output = tmp_path / "test.srt"
        result = mod.SRTExporter.export(segments, output)
        assert result == output
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "こんにちは" in content
        assert "00:00:00,000 --> 00:00:05,000" in content

    def test_export_vtt(self, tmp_path):
        mod = _import_module()
        segments = [
            {"start": 0.0, "end": 5.0, "text": "VTTテスト"},
        ]
        output = tmp_path / "test.vtt"
        result = mod.SRTExporter.export_vtt(segments, output)
        assert result == output
        content = output.read_text(encoding="utf-8")
        assert content.startswith("WEBVTT")
        assert "00:00:00.000 --> 00:00:05.000" in content

    def test_export_with_normalized_text(self, tmp_path):
        """text がなく normalized_text がある場合"""
        mod = _import_module()
        segments = [{"start": 0.0, "end": 1.0, "normalized_text": "フォールバック"}]
        output = tmp_path / "test.srt"
        mod.SRTExporter.export(segments, output)
        content = output.read_text(encoding="utf-8")
        assert "フォールバック" in content

    def test_export_with_normalized_segment_dataclass(self, tmp_path):
        """NormalizedSegmentオブジェクトを渡した場合の挙動"""
        mod = _import_module()
        seg = mod.NormalizedSegment(
            id="seg_001",
            start=1.5,
            end=4.2,
            original_text="テスト前",
            normalized_text="テスト後",
            corrections=[],
        )
        output = tmp_path / "dataclass_test.srt"
        mod.SRTExporter.export([seg], output)
        content = output.read_text(encoding="utf-8")
        assert "テスト後" in content
        assert "00:00:01,500 --> 00:00:04,200" in content

        output_vtt = tmp_path / "dataclass_test.vtt"
        mod.SRTExporter.export_vtt([seg], output_vtt)
        content_vtt = output_vtt.read_text(encoding="utf-8")
        assert "テスト後" in content_vtt
        assert "00:00:01.500 --> 00:00:04.200" in content_vtt

    def test_export_with_none_values(self, tmp_path):
        """text や normalized_text が None の場合でもクラッシュせず空文字列にフォールバックされることを検証"""
        mod = _import_module()
        segments = [
            {"start": 0.0, "end": 1.0, "text": None, "normalized_text": None},
            {"start": 1.0, "end": 2.0} # text も normalized_text も存在しない
        ]
        output = tmp_path / "none_test.srt"
        mod.SRTExporter.export(segments, output)
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:01,000" in content
        assert "00:00:01,000 --> 00:00:02,000" in content


class TestSubtitleNormalizer:
    """SubtitleNormalizer テスト（モック依存）"""

    def test_parse_response_valid_json(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        result = sn._parse_response('{"normalized_segments": [{"id": "seg_001", "text": "テスト"}], "uncertain_items": []}')
        assert len(result["normalized_segments"]) == 1

    def test_parse_response_invalid_json(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        with pytest.raises(ValueError):
            sn._parse_response("invalid json text")

    def test_parse_response_with_surrounding_text(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        result = sn._parse_response('Here is the result:\n{"normalized_segments": [], "uncertain_items": []}\nDone.')
        assert "normalized_segments" in result

    def test_fallback_normalize(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        segments = [
            {"id": "s1", "text": "テスト文"},
            {"text": "ID無しセグメント"}
        ]
        result = sn._fallback_normalize(segments)
        assert len(result["normalized_segments"]) == 2
        assert result["normalized_segments"][0]["id"] == "s1"
        assert result["normalized_segments"][1]["id"] == "seg_001"

    def test_apply_dictionary(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        result = {"normalized_segments": [{"text": "テスト", "corrections": []}]}
        updated = sn._apply_dictionary(result, [])
        assert "normalized_segments" in updated

    def test_normalize_success(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()

        mock_response = MagicMock()
        mock_response.text = '{"normalized_segments": [{"id": "seg_001", "text": "やまださん"}], "uncertain_items": []}'
        sn.client.models.generate_content.return_value = mock_response

        with patch.object(mod.proper_noun_dict.proper_noun_dict, 'get_all_entries', return_value=[{"incorrect": "やまだ", "correct": "山田"}]),              patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t.replace("やまだ", "山田"), [{"original": "やまだ", "replaced": "山田"}])):

            whisper_segments = [
                {"id": "seg_001", "text": "やまださん"}
            ]

            result = sn.normalize(whisper_segments, apply_dict=True)

            assert result["stats"]["total_segments"] == 1
            assert len(result["normalized_segments"]) == 1
            assert result["normalized_segments"][0]["text"] == "山田さん"
            assert len(result["normalized_segments"][0]["corrections"]) > 0

    def test_normalize_exception_propagates(self):
        """想定外の例外（RuntimeErrorなど）が発生した場合はフォールバックせず呼び出し元に伝播することを検証"""
        mod = _import_module()
        sn = mod.SubtitleNormalizer()

        sn.client.models.generate_content.side_effect = RuntimeError("Unexpected System Error")

        whisper_segments = [
            {"id": "seg_001", "text": "想定外エラー"}
        ]

        with pytest.raises(RuntimeError):
            sn.normalize(whisper_segments, apply_dict=True)

    def test_normalize_api_error_fallback(self):
        """APIErrorが発生した際に適切にフォールバックされることを検証"""
        from google.genai.errors import APIError
        mod = _import_module()
        sn = mod.SubtitleNormalizer()

        sn.client.models.generate_content.side_effect = APIError(code=500, response_json={})

        with patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t, [])):
            whisper_segments = [
                {"id": "seg_001", "text": "APIエラーフォールバック"}
            ]
            result = sn.normalize(whisper_segments, apply_dict=True)
            assert result["stats"]["total_segments"] == 1
            assert result["normalized_segments"][0]["text"] == "APIエラーフォールバック"

    def test_normalize_value_error_fallback(self):
        """ValueErrorが発生した際に適切にフォールバックされることを検証"""
        mod = _import_module()
        sn = mod.SubtitleNormalizer()

        sn.client.models.generate_content.side_effect = ValueError("Invalid Arguments")

        with patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t, [])):
            whisper_segments = [
                {"id": "seg_001", "text": "引数エラーフォールバック"}
            ]
            result = sn.normalize(whisper_segments, apply_dict=True)
            assert result["stats"]["total_segments"] == 1
            assert result["normalized_segments"][0]["text"] == "引数エラーフォールバック"

    def test_normalize_client_none_fallback(self):
        """clientがNoneの場合に適切にフォールバックされることを検証"""
        mod = _import_module()
        with patch("subtitle_normalizer.get_gemini_client", return_value=None):
            sn = mod.SubtitleNormalizer()
            with patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t, [])):
                whisper_segments = [
                    {"id": "seg_001", "text": "クライアントなしフォールバック"}
                ]
                result = sn.normalize(whisper_segments, apply_dict=True)
                assert result["stats"]["total_segments"] == 1
                assert result["normalized_segments"][0]["text"] == "クライアントなしフォールバック"

    def test_normalize_parse_error_fallback(self):
        """AIレスポンスのパースエラー時に適切にフォールバックされることを検証"""
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        
        mock_response = MagicMock()
        mock_response.text = "invalid json response"
        sn.client.models.generate_content.return_value = mock_response
        
        with patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t, [])):
            whisper_segments = [
                {"id": "seg_001", "text": "パースエラー時フォールバック"}
            ]
            result = sn.normalize(whisper_segments, apply_dict=True)
            assert result["stats"]["total_segments"] == 1
            assert result["normalized_segments"][0]["text"] == "パースエラー時フォールバック"

    def test_parse_response_json_decode_error(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        with pytest.raises(ValueError):
            sn._parse_response("{invalid_json_but_braces}")

    def test_lazy_initialization(self):
        """インスタンス生成時点ではクライアントやモデルの生成関数が呼ばれないことを検証"""
        mod = _import_module()
        with patch("subtitle_normalizer.get_gemini_client") as mock_get_client, \
             patch("subtitle_normalizer.get_model") as mock_get_model:
            sn = mod.SubtitleNormalizer()
            assert sn._client is None
            assert sn._model is None
            mock_get_client.assert_not_called()
            mock_get_model.assert_not_called()
            _ = sn.client
            mock_get_client.assert_called_once()
            _ = sn.model
            mock_get_model.assert_called_once_with("subtitle_split")

    def test_normalize_with_null_fields(self):
        """AIのレスポンスに null 値 (None) が含まれていた場合でも適切に空リスト等にフォールバックされることを検証"""
        mod = _import_module()
        sn = mod.SubtitleNormalizer()

        sn.client.models.generate_content.side_effect = None
        mock_response = MagicMock()
        mock_response.text = '{"normalized_segments": null, "uncertain_items": null}'
        sn.client.models.generate_content.return_value = mock_response

        whisper_segments = [{"id": "seg_001", "text": "テスト"}]
        result = sn.normalize(whisper_segments, apply_dict=True)
        assert result["stats"]["total_segments"] == 1
        assert result["stats"]["normalized_segments"] == 0
        assert result["stats"]["uncertain_items"] == 0


class TestConvenienceFunctions:
    """簡易関数テスト"""

    def test_export_srt_function(self, tmp_path):
        mod = _import_module()
        segments = [{"start": 0.0, "end": 1.0, "text": "テスト"}]
        result = mod.export_srt(segments, tmp_path / "out.srt")
        assert result.exists()

    def test_normalize_subtitles_convenience(self):
        mod = _import_module()

        mock_response = MagicMock()
        mock_response.text = '{"normalized_segments": [{"id": "seg_001", "text": "簡易関数テスト"}], "uncertain_items": []}'

        with patch.object(mod.subtitle_normalizer.client.models, 'generate_content', return_value=mock_response):
            whisper_segments = [{"id": "seg_001", "text": "簡易関数テスト"}]
            result = mod.normalize_subtitles(whisper_segments)
            assert len(result["normalized_segments"]) == 1
            assert result["normalized_segments"][0]["text"] == "簡易関数テスト"


    def test_format_cue_timestamps(self):
        mod = _import_module()
        exporter = mod.SRTExporter
        segment = {"start": 1.234, "end": 5.678}
        
        # 通常のSRT形式
        start, end = exporter._format_cue_timestamps(segment, is_vtt=False)
        assert start == "00:00:01,234"
        assert end == "00:00:05,678"

        # WebVTT形式
        start_vtt, end_vtt = exporter._format_cue_timestamps(segment, is_vtt=True)
        assert start_vtt == "00:00:01.234"
        assert end_vtt == "00:00:05.678"

    def test_extract_cue_text(self):
        mod = _import_module()
        exporter = mod.SRTExporter
        
        # 'text' キーが存在する場合
        segment_text = {"text": "こんにちは"}
        assert exporter._extract_cue_text(segment_text) == "こんにちは"

        # 'normalized_text' キーが存在する場合
        segment_norm = {"normalized_text": "さようなら"}
        assert exporter._extract_cue_text(segment_norm) == "さようなら"

        # どちらも存在しない場合
        segment_none = {}
        assert exporter._extract_cue_text(segment_none) == ""

    def test_write_file_content(self, tmp_path):
        mod = _import_module()
        exporter = mod.SRTExporter
        output_file = tmp_path / "test_write.txt"
        lines = ["line1", "line2", "line3"]
        
        exporter._write_file_content(lines, output_file)
        assert output_file.exists()
        with open(output_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == "line1\nline2\nline3"