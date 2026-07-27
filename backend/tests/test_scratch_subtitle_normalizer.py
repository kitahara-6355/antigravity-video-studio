"""
test_scratch_subtitle_normalizer.py — subtitle_normalizer.py のテスト
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

class TestScratchSRTExporter:
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
        mod = _import_module()
        segments = [{"start": 0.0, "end": 1.0, "normalized_text": "フォールバック"}]
        output = tmp_path / "test.srt"
        mod.SRTExporter.export(segments, output)
        content = output.read_text(encoding="utf-8")
        assert "フォールバック" in content

class TestScratchSubtitleNormalizer:
    """SubtitleNormalizer テスト（モック依存）"""

    def test_dataclasses(self):
        mod = _import_module()
        seg = mod.NormalizedSegment(
            id="seg_001",
            start=0.0,
            end=1.0,
            original_text="テスト",
            normalized_text="てすと",
            corrections=[]
        )
        assert seg.id == "seg_001"
        
        item = mod.UncertainItem(
            original="テスト",
            candidates=["候補1"],
            context="文脈",
            segment_id="seg_001",
            confidence=0.5
        )
        assert item.original == "テスト"

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
        
        with patch.object(mod.proper_noun_dict.proper_noun_dict, 'get_all_entries', return_value=[{"incorrect": "やまだ", "correct": "山田"}]), \
             patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t.replace("やまだ", "山田"), [{"original": "やまだ", "replaced": "山田"}])):
            
            whisper_segments = [
                {"id": "seg_001", "text": "やまださん"}
            ]
            
            result = sn.normalize(whisper_segments, apply_dict=True)
            
            assert result["stats"]["total_segments"] == 1
            assert len(result["normalized_segments"]) == 1
            assert result["normalized_segments"][0]["text"] == "山田さん"
            assert len(result["normalized_segments"][0]["corrections"]) > 0

    def test_normalize_no_apply_dict(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        
        mock_response = MagicMock()
        mock_response.text = '{"normalized_segments": [{"id": "seg_001", "text": "やまださん"}], "uncertain_items": []}'
        sn.client.models.generate_content.return_value = mock_response
        
        whisper_segments = [
            {"id": "seg_001", "text": "やまださん"}
        ]
        
        result = sn.normalize(whisper_segments, apply_dict=False)
        assert result["stats"]["total_segments"] == 1

    def test_normalize_exception_fallback(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        
        sn.client.models.generate_content.side_effect = mod.APIError(code=500, response_json={})
        
        with patch.object(mod, 'apply_dictionary', side_effect=lambda t: (t, [])):
            whisper_segments = [
                {"id": "seg_001", "text": "エラー時フォールバック"}
            ]
            
            result = sn.normalize(whisper_segments, apply_dict=True)
            
            assert result["stats"]["total_segments"] == 1
            assert result["normalized_segments"][0]["text"] == "エラー時フォールバック"

    def test_normalize_parse_error_fallback(self):
        mod = _import_module()
        sn = mod.SubtitleNormalizer()
        
        mock_response = MagicMock()
        mock_response.text = "invalid non-json text"
        sn.client.models.generate_content.side_effect = None
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

class TestScratchConvenienceFunctions:
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
