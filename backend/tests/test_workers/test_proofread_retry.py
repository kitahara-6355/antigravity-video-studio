"""
P-02: AI校閲リトライ統計テスト

ai_proofreader.proofread_segments の FIX-2A リトライロジックを検証する。
- 429/503エラー時の指数バックオフリトライ
- リトライ成功時の正常復帰
- リトライ上限到達時のgraceful degradation
- return_stats=True によるリトライ統計の取得
- pipeline_coordinator との統合（ctx.warnings伝搬）
"""

import sys
import os
import copy
import json
import time as time_module
import pytest
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_success_response(corrections):
    """成功レスポンスを生成"""
    mock_response = MagicMock()
    mock_response.text = json.dumps(corrections)
    return mock_response


def _run_proofread_with_mock(segments, api_side_effects, return_stats=True):
    """共通テストヘルパー: モック環境でproofread_segmentsを実行する"""
    from subtitle_engine.ai_proofreader import proofread_segments

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = api_side_effects

    # model_governance.get_governed_client をモック（成功 → mock_clientを返す）
    with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-test"):
        with patch("subtitle_engine.ai_proofreader._build_proper_noun_context", return_value=""):
            with patch("model_governance.get_governed_client", return_value=mock_client):
                # time.sleep は ai_proofreader 内で `import time as _time` されるので
                # builtinのtimeモジュールをパッチ
                with patch("time.sleep", return_value=None):
                    return proofread_segments(
                        segments,
                        return_stats=return_stats,
                    )


class TestProofreadRetryStats:
    """return_stats=True によるリトライ統計の検証"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_retry_on_429_then_succeed(self):
        """429エラー後にリトライして成功する"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                Exception("429 Resource Exhausted"),
                _make_success_response([{"index": 0, "text": "修正後テスト文"}]),
            ],
        )

        assert stats["total_retries"] == 1
        assert stats["failed_batches"] == 0
        assert stats["total_batches"] == 1
        assert stats["skipped"] is False
        assert result[0]["text"] == "修正後テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_retry_exhausted_batch_fails(self):
        """リトライ上限到達でバッチ失敗扱いになる"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                Exception("429 Resource Exhausted"),
                Exception("429 Resource Exhausted"),
                Exception("429 Resource Exhausted"),
                Exception("429 Resource Exhausted"),
            ],
        )

        assert stats["total_retries"] == 3  # 3回リトライ（初回は含まない）
        assert stats["failed_batches"] == 1
        assert stats["total_batches"] == 1
        assert stats["skipped"] is False
        assert result[0]["text"] == "テスト文"  # 元のテキストが保持される

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_non_retryable_error_no_retry(self):
        """リトライ対象外エラーはリトライしない"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        result, stats = _run_proofread_with_mock(
            segments,
            [ValueError("JSON parse error")],
        )

        assert stats["total_retries"] == 0
        assert stats["failed_batches"] == 1
        assert result[0]["text"] == "テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_503_service_unavailable_retry(self):
        """503 Service Unavailable がリトライ対象になる"""
        segments = [{"text": "テスト", "start": 0, "end": 3}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                Exception("503 Service Unavailable"),
                _make_success_response([{"index": 0, "text": "修正後"}]),
            ],
        )

        assert stats["total_retries"] == 1
        assert stats["failed_batches"] == 0

    def test_no_api_key_skipped(self):
        """APIキーなしでスキップされる"""
        from subtitle_engine.ai_proofreader import proofread_segments

        env = {k: v for k, v in os.environ.items()
               if k not in ("GOOGLE_GENERATIVE_AI_API_KEY", "GOOGLE_API_KEY")}

        with patch.dict(os.environ, env, clear=True):
            result, stats = proofread_segments(
                [{"text": "テスト", "start": 0, "end": 3}],
                return_stats=True,
            )

        assert stats["skipped"] is True
        assert stats["total_retries"] == 0

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_backward_compat_no_stats(self):
        """return_stats=False（デフォルト）では従来通りリストを返す"""
        segments = [{"text": "テスト", "start": 0, "end": 3}]
        result = _run_proofread_with_mock(
            segments,
            [_make_success_response([{"index": 0, "text": "OK"}])],
            return_stats=False,
        )

        assert isinstance(result, list)
        assert result[0]["text"] == "OK"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_quota_exhausted_retry(self):
        """quota exhausted がリトライ対象になる"""
        segments = [{"text": "テスト", "start": 0, "end": 3}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                Exception("Quota exceeded for project"),
                _make_success_response([{"index": 0, "text": "修正後"}]),
            ],
        )

        assert stats["total_retries"] == 1
        assert stats["failed_batches"] == 0


class TestProofreadRetryIntegration:
    """pipeline_coordinator.ProofreadWorker とのリトライ統計連携"""

    @pytest.mark.asyncio
    async def test_retry_warnings_propagated_to_ctx(self):
        """リトライ失敗時にctx.warningsに反映される"""
        from fixtures.mock_pipeline import create_mock_ctx
        from agents.pipeline_coordinator import ProofreadWorker

        ctx = create_mock_ctx(segments=3)
        original_segments = copy.deepcopy(ctx.segments)

        mock_stats = {
            "proofread_count": 0,
            "total_retries": 3,
            "failed_batches": 1,
            "total_batches": 1,
            "skipped": False,
        }

        with patch(
            "subtitle_engine.ai_proofreader.proofread_segments",
            return_value=(original_segments, mock_stats),
        ):
            worker = ProofreadWorker()
            result = await worker.execute(ctx)

        retry_warnings = [w for w in ctx.warnings if "バッチ" in w]
        assert len(retry_warnings) >= 1, f"リトライ警告がctx.warningsに存在しない: {ctx.warnings}"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_warnings_on_clean_run(self):
        """リトライなし・失敗なしの場合、追加warningは生成しない"""
        from fixtures.mock_pipeline import create_mock_ctx
        from agents.pipeline_coordinator import ProofreadWorker

        ctx = create_mock_ctx(segments=3)
        original_segments = copy.deepcopy(ctx.segments)

        mock_stats = {
            "proofread_count": 2,
            "total_retries": 0,
            "failed_batches": 0,
            "total_batches": 1,
            "skipped": False,
        }

        with patch(
            "subtitle_engine.ai_proofreader.proofread_segments",
            return_value=(original_segments, mock_stats),
        ):
            worker = ProofreadWorker()
            result = await worker.execute(ctx)

        retry_warnings = [w for w in ctx.warnings if "リトライ" in w or "バッチ" in w]
        assert len(retry_warnings) == 0
        assert result.success is True


class TestProofreadRobustness:
    """具体的例外キャッチによる耐障害性とロバストネスの検証"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_proper_noun_dict_import_error(self):
        """proper_noun_dict インポートエラー時にデフォルトの校閲コンテキストを返す"""
        from subtitle_engine.ai_proofreader import _build_proper_noun_context
        
        # builtins.__import__ を部分的にモックして ImportError を発生させる
        original_import = __import__
        def mock_import(name, *args, **kwargs):
            if name == "proper_noun_dict":
                raise ImportError("mock import error")
            return original_import(name, *args, **kwargs)
            
        with patch("builtins.__import__", side_effect=mock_import):
            context = _build_proper_noun_context()
            assert "固有名詞辞書" in context
            assert "利用できません" in context or "失敗" in context

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_proper_noun_dict_attribute_error(self):
        """proper_noun_dict.get_all_entries が AttributeError を投げた時、デフォルトのコンテキストを返す"""
        from subtitle_engine.ai_proofreader import _build_proper_noun_context
        
        # mock_dict のメソッドが AttributeError を投げるようにパッチする
        mock_dict = MagicMock()
        mock_dict.get_all_entries.side_effect = AttributeError("mock attribute error")
        with patch.dict(sys.modules, {"proper_noun_dict": MagicMock(proper_noun_dict=mock_dict)}):
            context = _build_proper_noun_context()
            assert "固有名詞辞書" in context
            assert "解析に失敗" in context or "失敗" in context

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_api_error_retryable_429(self):
        """APIError(code=429)が投げられた時、正しくリトライされる"""
        from google.genai.errors import APIError
        # APIErrorを code と response_json を指定して作成
        mock_api_error = APIError(429, response_json='{"error": {"code": 429, "message": "Resource Exhausted"}}')
        mock_api_error.code = 429
        
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                mock_api_error,
                _make_success_response([{"index": 0, "text": "修正後テスト文"}]),
            ],
        )

        assert stats["total_retries"] == 1
        assert stats["failed_batches"] == 0
        assert result[0]["text"] == "修正後テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_network_error_retryable(self):
        """ConnectionErrorが投げられた時、正しくリトライされる"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        result, stats = _run_proofread_with_mock(
            segments,
            [
                ConnectionError("Temporary connection lost"),
                _make_success_response([{"index": 0, "text": "修正後テスト文"}]),
            ],
        )

        assert stats["total_retries"] == 1
        assert stats["failed_batches"] == 0
        assert result[0]["text"] == "修正後テスト文"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_record_api_call_import_error(self):
        """API使用量トラッカーのインポートエラー時に処理が続行される"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        
        original_import = __import__
        def mock_import(name, *args, **kwargs):
            if "usage_tracker" in name:
                raise ImportError("Mocked tracker import error")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result, stats = _run_proofread_with_mock(
                segments,
                [_make_success_response([{"index": 0, "text": "修正後テスト文"}])],
            )
            assert stats["skipped"] is False
            assert result[0]["text"] == "修正後テスト文"



class TestProofreadCoverageExpansion:
    """追加のカバレッジ向上のためのテスト"""

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_proper_noun_context_with_entries(self):
        """辞書に正常なエントリが存在する場合のコンテキスト生成を検証"""
        from subtitle_engine.ai_proofreader import _build_proper_noun_context
        import sys

        mock_entries = [
            {"incorrect": "きたはら", "correct": "北原", "context_hint": "人名"},
            {"incorrect": "きたひろ", "correct": "喜多広", "context_hint": ""}
        ]
        mock_dict = MagicMock()
        mock_dict.get_all_entries.return_value = mock_entries

        # mock_dict を sys.modules にパッチする
        with patch.dict(sys.modules, {"proper_noun_dict": MagicMock(proper_noun_dict=mock_dict, apply_dictionary=MagicMock())}):
            context = _build_proper_noun_context()
            assert "北原" in context
            assert "喜多広" in context

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_proofread_with_callback(self):
        """update_callback が正常に呼び出されることを検証"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        callback_calls = []

        def mock_callback(status, msg, progress):
            callback_calls.append((status, msg, progress))

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _make_success_response([{"index": 0, "text": "修正後"}])

        with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-test"):
            with patch("subtitle_engine.ai_proofreader._build_proper_noun_context", return_value=""):
                with patch("model_governance.get_governed_client", return_value=mock_client):
                    with patch("time.sleep", return_value=None):
                        from subtitle_engine.ai_proofreader import proofread_segments
                        result = proofread_segments(segments, update_callback=mock_callback)

        assert len(callback_calls) > 0
        assert callback_calls[0][0] == "processing"
        assert "AI校閲を実行中" in callback_calls[0][1]

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_record_api_call_os_error(self):
        """API使用量記録で OSError が発生しても処理が継続することを検証"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        
        with patch("usage_tracker.api_usage_tracker.record_api_call", side_effect=OSError("Disk full")):
            result, stats = _run_proofread_with_mock(
                segments,
                [_make_success_response([{"index": 0, "text": "修正後"}])],
            )
            assert stats["skipped"] is False
            assert result[0]["text"] == "修正後"

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
    def test_record_api_call_value_error(self):
        """API使用量記録で ValueError が発生しても処理が継続することを検証"""
        segments = [{"text": "テスト文", "start": 0, "end": 5}]
        
        with patch("usage_tracker.api_usage_tracker.record_api_call", side_effect=ValueError("Invalid args")):
            result, stats = _run_proofread_with_mock(
                segments,
                [_make_success_response([{"index": 0, "text": "修正後"}])],
            )
            assert stats["skipped"] is False
            assert result[0]["text"] == "修正後"
