"""
T-batch_e022e0-security-001: AI校閲セキュリティおよびインプットバリデーションテスト
"""

import sys
import os
import pytest
import json
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def _make_response(text_content):
    """レスポンスオブジェクトを模擬"""
    mock_resp = MagicMock()
    mock_resp.text = text_content
    return mock_resp

def _run_proofread_with_mock(segments, api_side_effects, return_stats=True):
    from subtitle_engine.ai_proofreader import proofread_segments
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = api_side_effects

    with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-test"):
        with patch("subtitle_engine.ai_proofreader._build_proper_noun_context", return_value=""):
            with patch("model_governance.get_governed_client", return_value=mock_client):
                with patch("time.sleep", return_value=None):
                    return proofread_segments(segments, return_stats=return_stats)

class TestProofreadInputValidation:
    """入力引数 segments のバリデーション検証"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_invalid_segments_type(self):
        """segments がリストでない場合は処理をスキップし、元のデータを返す"""
        res, stats = _run_proofread_with_mock({"text": "test"}, [], return_stats=True)
        assert stats["skipped"] is True
        assert res == {"text": "test"}

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_invalid_segment_element_type(self):
        """segments の要素が辞書でない場合はスキップ"""
        res, stats = _run_proofread_with_mock(["invalid_element"], [], return_stats=True)
        assert stats["skipped"] is True
        assert res == ["invalid_element"]

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_missing_text_key(self):
        """segments の要素に text キーがない場合はスキップ"""
        res, stats = _run_proofread_with_mock([{"start": 0}], [], return_stats=True)
        assert stats["skipped"] is True
        assert res == [{"start": 0}]

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_invalid_text_type(self):
        """text が文字列ではない場合はスキップ"""
        res, stats = _run_proofread_with_mock([{"text": 123}], [], return_stats=True)
        assert stats["skipped"] is True
        assert res == [{"text": 123}]


class TestProofreadLLMResponseValidation:
    """LLM レスポンスのバリデーションおよびセキュリティ検証"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_invalid_json_format(self):
        """LLMの返却値が不正なJSONの場合はリトライせず即時バッチ失敗"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response("invalid json string")],
            return_stats=True
        )
        assert stats["failed_batches"] == 1
        assert stats["total_retries"] == 0
        assert res[0]["text"] == "テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_response_is_not_list(self):
        """LLMの返却値がリストではない場合は無視"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response(json.dumps({"index": 0, "text": "修正後"}))],
            return_stats=True
        )
        assert stats["failed_batches"] == 0
        assert res[0]["text"] == "テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_response_out_of_range_index(self):
        """範囲外の index が返された場合は無視"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response(json.dumps([{"index": 1, "text": "範囲外"}]))],
            return_stats=True
        )
        assert res[0]["text"] == "テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_response_index_string_cast(self):
        """文字列型の index も安全にキャストして処理される"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response(json.dumps([{"index": "0", "text": "修正後"}]))],
            return_stats=True
        )
        assert res[0]["text"] == "修正後"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_response_missing_keys(self):
        """必要なキーが欠落している要素は無視"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response(json.dumps([{"index": 0}]))],
            return_stats=True
        )
        assert res[0]["text"] == "テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_response_invalid_text_type(self):
        """text が文字列ではない要素は無視"""
        segments = [{"text": "テスト文"}]
        res, stats = _run_proofread_with_mock(
            segments,
            [_make_response(json.dumps([{"index": 0, "text": 1234}]))],
            return_stats=True
        )
        assert res[0]["text"] == "テスト文"
