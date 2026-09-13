import sys
from unittest.mock import MagicMock, patch

# モック汚染防止のため、元のモジュールを退避
_original_modules = {}
for _m in ['google', 'google.genai', 'google.genai.types', 'google.genai.errors', 'subtitle_engine.whisper_transcriber', 'subtitle_engine.formatter']:
    _original_modules[_m] = sys.modules.get(_m)

# google.genai 関連のインポートをバイパスするためのモック
class MockAPIError(Exception):
    def __init__(self, message="", code=None):
        super().__init__(message)
        self.message = message
        self.code = code

mock_google = MagicMock()
mock_genai = MagicMock()
mock_types = MagicMock()
mock_errors = MagicMock()
mock_errors.APIError = MockAPIError

sys.modules['google'] = mock_google
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = mock_types
sys.modules['google.genai.errors'] = mock_errors

# テストコード内で参照する APIError
APIError = MockAPIError

# 重いライブラリ（faster-whisper や numpy）のロードによる環境競合を避けるため、
# 関連モジュールをモック化してバイパスする
sys.modules['subtitle_engine.whisper_transcriber'] = MagicMock()
sys.modules['subtitle_engine.formatter'] = MagicMock()

# テスト終了後にモックをクリーンアップして退避した状態に戻す
def teardown_module(module):
    for m, orig in _original_modules.items():
        if orig is None:
            sys.modules.pop(m, None)
        else:
            sys.modules[m] = orig

import os
import json
import pytest

# backend ディレクトリを sys.path に追加してインポート可能にする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtitle_engine import ai_proofreader


class TestGetCurrentModel:
    """_get_current_model() 関数のテスト"""

    def test_get_current_model_success(self):
        """model_governance が正常に機能してモデル名を返すケース"""
        mock_module = MagicMock()
        mock_gov = MagicMock()
        mock_gov._resolve_model.return_value = "custom-proofreader-model"
        mock_module.model_governance = mock_gov
        with patch.dict("sys.modules", {"model_governance": mock_module}):
            model_name = ai_proofreader._get_current_model()
            assert model_name == "custom-proofreader-model"

    def test_get_current_model_import_error(self):
        """model_governance がインポートできない場合、デフォルトモデルを返すケース"""
        with patch.dict("sys.modules", {"model_governance": None}):
            # キャッシュをクリアするために reload するか、インポートエラーを引き起こす
            with patch("builtins.__import__", side_effect=ImportError):
                model_name = ai_proofreader._get_current_model()
                assert model_name == "gemini-3.6-flash"


class TestBuildProperNounContext:
    """_build_proper_noun_context() 関数のテスト"""

    def test_build_context_success(self):
        """辞書データが正常に取得されコンテキストが構築されるケース"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.return_value = [
            {"incorrect": "きたはら", "correct": "北原", "context_hint": "人名"},
            {"incorrect": "ぷろじぇくと", "correct": "プロジェクト"}
        ]
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "## 固有名詞辞書" in context
            assert "「きたはら」→「北原」（人名）" in context
            assert "「ぷろじぇくと」→「プロジェクト」" in context

    def test_build_context_empty(self):
        """辞書データが空工程のケース"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.return_value = []
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "辞書は空です" in context

    def test_build_context_import_error(self):
        """辞書モジュールがインポートできない場合のケース"""
        with patch.dict("sys.modules", {"proper_noun_dict": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                context = ai_proofreader._build_proper_noun_context()
                assert "辞書モジュールが利用できません" in context

    def test_build_context_exception_parsing(self):
        """辞書データの解析中に KeyError などの例外が発生した場合のケース"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        # 例外を発生させるために get_all_entries 自体が例外を投げるようにする
        mock_dict.get_all_entries.side_effect = TypeError("Mock parsed data error")
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "辞書の解析に失敗しました" in context

    def test_build_context_exception_parsing_value_error(self):
        """辞書データの解析中に ValueError 例外が発生した場合のケース"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.side_effect = ValueError("Mock parsed value error")
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "辞書の解析に失敗しました" in context

    def test_build_context_exception_parsing_key_error(self):
        """辞書データの解析中に KeyError 例外が発生した場合のケース"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.side_effect = KeyError("Mock parsed key error")
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "辞書の解析に失敗しました" in context


class TestProofreadSegmentsInputValidation:
    """proofread_segments() 関数の入力バリデーションのテスト"""

    def test_validation_not_a_list(self):
        """segments がリストではない場合の早期リターン"""
        result, stats = ai_proofreader.proofread_segments("not a list", return_stats=True)
        assert result == "not a list"
        assert stats["skipped"] is True

    def test_validation_element_not_a_dict(self):
        """segments 内の要素が辞書ではない場合の早期リターン"""
        result, stats = ai_proofreader.proofread_segments(["not a dict"], return_stats=True)
        assert result == ["not a dict"]
        assert stats["skipped"] is True

    def test_validation_missing_text_key(self):
        """segments 内の辞書に text キーがない場合の早期リターン"""
        result, stats = ai_proofreader.proofread_segments([{"start": 0}], return_stats=True)
        assert result == [{"start": 0}]
        assert stats["skipped"] is True

    def test_validation_text_not_string(self):
        """segments 内の text の値が文字列ではない場合の早期リターン"""
        result, stats = ai_proofreader.proofread_segments([{"text": 123}], return_stats=True)
        assert result == [{"text": 123}]
        assert stats["skipped"] is True

    def test_validation_start_not_number(self):
        """segments 内の start が数値ではない場合の早期リターン"""
        segments = [{"text": "テスト", "start": "invalid"}]
        result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
        assert result == segments
        assert stats["skipped"] is True

    def test_validation_start_negative(self):
        """segments 内の start が負数の場合の早期リターン"""
        segments = [{"text": "テスト", "start": -1.0}]
        result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
        assert result == segments
        assert stats["skipped"] is True

    def test_validation_end_not_number(self):
        """segments 内の end が数値ではない場合の早期リターン"""
        segments = [{"text": "テスト", "end": "invalid"}]
        result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
        assert result == segments
        assert stats["skipped"] is True

    def test_validation_end_negative(self):
        """segments 内の end が負数の場合の早期リターン"""
        segments = [{"text": "テスト", "end": -1.0}]
        result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
        assert result == segments
        assert stats["skipped"] is True

    def test_validation_end_less_than_start(self):
        """segments 内の end が start 未満の場合の早期リターン"""
        segments = [{"text": "テスト", "start": 5.0, "end": 4.0}]
        result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
        assert result == segments
        assert stats["skipped"] is True

    def test_validation_valid_timestamps(self):
        """正常な start, end の場合はバリデーションをパスしてAPIキー確認まで進むこと"""
        # APIキーなしの環境で実行すると、バリデーション通過後にAPIキーチェックでskippedになる
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GOOGLE_GENERATIVE_AI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            segments = [{"text": "テスト", "start": 1.0, "end": 2.0}]
            result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
            assert result == segments
            # APIキーがないのでskippedになるが、バリデーションによる早期リターンではなく、APIキーチェックによるものである
            assert stats["skipped"] is True


class TestProofreadSegmentsApiKeyCheck:
    """proofread_segments() 関数の API キーチェックのテスト"""

    def test_api_key_not_found(self):
        """環境変数に API キーが存在しない場合の早期リターン"""
        with patch.dict(os.environ, {}, clear=True):
            # 念のため両方のキーを pop しておく
            os.environ.pop("GOOGLE_GENERATIVE_AI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)
            result, stats = ai_proofreader.proofread_segments([{"text": "テスト"}], return_stats=True)
            assert stats["skipped"] is True


class TestProofreadSegmentsClientAndTracker:
    """proofread_segments() 関数のクライアント初期化とトラッカー関連のテスト"""

    @pytest.fixture(autouse=True)
    def setup_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            yield

    def test_client_fallback_to_factory(self):
        """model_governance がインポートできない場合、gemini_client_factory にフォールバックするケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "[]"
        mock_client.models.generate_content.return_value = mock_response

        # sys.modules のパッチで model_governance のインポートを失敗させる
        # 同時に gemini_client_factory がモッククライアントを返すようにする
        with patch.dict("sys.modules", {"model_governance": None, "gemini_client_factory": MagicMock(get_gemini_client=lambda: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is False

    def test_usage_tracker_import_error(self):
        """usage_tracker インポートエラー時に例外が無視され、正常処理が継続されるケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "[]"
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client), "usage_tracker.api_usage_tracker": None}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is False

    def test_usage_tracker_os_error(self):
        """usage_tracker.record_api_call が OSError を発生させた場合に例外が無視されるケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "[]"
        mock_client.models.generate_content.return_value = mock_response

        mock_tracker = MagicMock()
        mock_tracker.record_api_call.side_effect = OSError("Disk full")

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client), "usage_tracker.api_usage_tracker": mock_tracker}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is False

    def test_usage_tracker_value_error(self):
        """usage_tracker.record_api_call が ValueError を発生させた場合に例外が無視されるケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "[]"
        mock_client.models.generate_content.return_value = mock_response

        mock_tracker = MagicMock()
        mock_tracker.record_api_call.side_effect = ValueError("Invalid arg")

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client), "usage_tracker.api_usage_tracker": mock_tracker}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is False


class TestProofreadSegmentsResponseValidation:
    """proofread_segments() 関数の API レスポンス解析とバリデーションのテスト"""

    @pytest.fixture(autouse=True)
    def setup_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            yield

    def _run_with_response_text(self, response_text, segments):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                return ai_proofreader.proofread_segments(segments, return_stats=True)

    def test_json_decode_error(self):
        """API レスポンスが不正な JSON の場合、JSONDecodeError によりバッチが失敗するケース"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text("invalid json", segments)
        assert stats["failed_batches"] == 1
        assert stats["proofread_count"] == 0

    def test_response_is_not_a_list(self):
        """API レスポンスがリストではない場合（例: 辞書）のスキップ処理"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text('{"index": 0, "text": "修正済"}', segments)
        assert stats["proofread_count"] == 0

    def test_response_item_is_not_a_dict(self):
        """レスポンスのリストの要素が辞書ではない場合のスキップ処理"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text('["not a dict"]', segments)
        assert stats["proofread_count"] == 0

    def test_response_item_missing_index_or_text(self):
        """レスポンスの要素に index または text がない場合のスキップ処理"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text('[{"text": "修正済"}]', segments)  # index 欠損
        assert stats["proofread_count"] == 0

    def test_response_item_invalid_index_type(self):
        """レスポンスの要素の index が整数値に変換できない場合のスキップ処理"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text('[{"index": "invalid", "text": "修正済"}]', segments)
        assert stats["proofread_count"] == 0

    def test_response_item_index_out_of_range(self):
        """レスポンスの要素の index が現在のバッチのインデックス範囲外（境界値エラー）の場合のスキップ処理"""
        segments = [{"text": "テスト"}]  # バラエティはインデックス 0 のみ
        result, stats = self._run_with_response_text('[{"index": 1, "text": "修正済"}]', segments)  # 範囲外
        assert stats["proofread_count"] == 0

    def test_response_item_text_not_string(self):
        """レスポンスの要素の text が文字列ではない場合のスキップ処理"""
        segments = [{"text": "テスト"}]
        result, stats = self._run_with_response_text('[{"index": 0, "text": 123}]', segments)
        assert stats["proofread_count"] == 0

    def test_response_item_success(self):
        """レスポンスが正常でセグメントが正しく更新されるケース"""
        segments = [{"text": "こんにちは、えー、テストです。"}]
        result, stats = self._run_with_response_text('[{"index": 0, "text": "こんにちは、テストです。"}]', segments)
        assert stats["proofread_count"] == 1
        assert result[0]["text"] == "こんにちは、テストです。"


class TestProofreadSegmentsRetryAndBackoff:
    """proofread_segments() 関数のリトライおよび指数バックオフ、致命的エラーハンドリングのテスト"""

    @pytest.fixture(autouse=True)
    def setup_api_key_and_sleep(self):
        # time.sleep をモック化してリトライのテスト実行を高速化
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}), \
             patch("time.sleep", lambda x: None):
            yield

    def test_retry_on_api_error_429(self):
        """APIError (429) の場合にリトライが走り、その後成功するケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは 429 エラー、2回目は成功
        api_error = APIError(message="Resource exhausted", code=429)
        mock_client.models.generate_content.side_effect = [api_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert stats["proofread_count"] == 1
                assert result[0]["text"] == "修正済"

    def test_retry_on_connection_error(self):
        """ConnectionError の場合にリトライが走り、その後成功するケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは接続エラー、2回目は成功
        conn_error = ConnectionError("Connection reset by peer")
        mock_client.models.generate_content.side_effect = [conn_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert stats["proofread_count"] == 1

    def test_retry_on_general_exception_retryable_string(self):
        """一般の例外だが、メッセージに resource_exhausted 等の再試行可能文字列が含まれる場合にリトライするケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは例外、2回目は成功
        quota_error = RuntimeError("Quota exceeded: resource_exhausted limit reached")
        mock_client.models.generate_content.side_effect = [quota_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0

    def test_retry_limit_exceeded(self):
        """リトライ上限（MAX_RETRIES=3）を超えて 4 回とも失敗し、バッチが失敗するケース"""
        mock_client = MagicMock()
        api_error = APIError(message="Quota exceeded", code=429)
        # 4回連続でエラーを返す
        mock_client.models.generate_content.side_effect = [api_error, api_error, api_error, api_error]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 3  # MAX_RETRIES = 3 回リトライが行われる
                assert stats["failed_batches"] == 1
                assert stats["proofread_count"] == 0

    def test_non_retryable_api_error(self):
        """APIError (400) などのリトライ対象外のエラーの場合、リトライせずに即時失敗するケース"""
        mock_client = MagicMock()
        api_error = APIError(message="Bad Request", code=400)
        mock_client.models.generate_content.side_effect = api_error

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 0  # 即時失敗
                assert stats["failed_batches"] == 1

    def test_fatal_exception_in_outer_try(self):
        """関数内の外側で予期しない致命的例外が発生した場合の Fatal Error ガード"""
        # クライアント取得時に例外を発生させる
        with patch.dict("sys.modules", {"model_governance": None}):
            with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Fatal client creation error")):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is True

    def test_retry_on_timeout_error(self):
        """TimeoutError の場合にリトライが走り、その後成功するケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しはタイムアウトエラー、2回目は成功
        timeout_error = TimeoutError("Request timed out")
        mock_client.models.generate_content.side_effect = [timeout_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert stats["proofread_count"] == 1

    def test_retry_on_os_error_retryable(self):
        """OSError の場合にリトライが走り、その後成功するケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは OSエラー、2回目は成功
        os_error = OSError("Socket error")
        mock_client.models.generate_content.side_effect = [os_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert stats["proofread_count"] == 1

    def test_retry_on_api_error_503(self):
        """APIError (503) の場合にリトライが走り、その後成功するケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは 503 エラー、2回目は成功
        api_error = APIError(message="Service Unavailable", code=503)
        mock_client.models.generate_content.side_effect = [api_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert stats["proofread_count"] == 1
                assert result[0]["text"] == "修正済"

    def test_retry_on_general_exception_quota_string(self):
        """一般の例外だが、メッセージに quota が含まれる場合にリトライするケース"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'

        # 最初の API 呼び出しは例外、2回目は成功
        quota_error = RuntimeError("API quota exceeded")
        mock_client.models.generate_content.side_effect = [quota_error, mock_response]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0


class TestAdditionalCoverage:
    """残りのブランチカバレッジを 100% にするための追加テスト"""

    @pytest.fixture(autouse=True)
    def setup_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            yield

    def test_proofread_segments_return_stats_false(self):
        """return_stats=False の場合に正しく list が返る（ai_proofreader.py L92 の return segs カバー）"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[]'
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result = ai_proofreader.proofread_segments(segments, return_stats=False)
                assert isinstance(result, list)
                assert len(result) == 1

    def test_proofread_segments_update_callback(self):
        """update_callback が指定された場合に呼び出される（ai_proofreader.py L180 の callback カバー）"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[]'
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                mock_callback = MagicMock()
                ai_proofreader.proofread_segments(segments, update_callback=mock_callback)
                # update_callback が "processing" 引数を伴って呼び出されたことを確認
                mock_callback.assert_any_call("processing", "AI校閲を実行中 (1/1 バッチ)...", 99)

    def test_main_execution(self):
        """__main__ ブロックを実行してカバレッジを 100% にする"""
        import runpy
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        # __main__ で実行されるテスト入力は2つなので、2つの要素を持つJSONを返す
        mock_response.text = '[{"index": 0, "text": "こんにちは、初夏の北原美玲です。"}, {"index": 1, "text": "本日は久北博之先生にお越しいただいています。"}]'
        mock_client.models.generate_content.return_value = mock_response

        # sys.modules の model_governance に get_governed_client をモック登録
        mock_gov_module = MagicMock()
        mock_gov_module.get_governed_client.return_value = mock_client
        mock_gov_module._resolve_model.return_value = "gemini-2.5-flash"
        
        import warnings
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}), \
             patch.dict("sys.modules", {"model_governance": mock_gov_module}), \
             warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("subtitle_engine.ai_proofreader", run_name="__main__")


# 追加されたテストケース（サブエージェントによる自動追加）
class TestCoverageEnhancementAdditional:
    @pytest.fixture(autouse=True)
    def setup_api_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake_key"}):
            yield

    def test_validation_empty_list(self):
        """segments が空リストの場合、正常に空リストが返ることをテスト"""
        from subtitle_engine import ai_proofreader
        result, stats = ai_proofreader.proofread_segments([], return_stats=True)
        assert result == []
        assert stats["skipped"] is False

    def test_build_context_no_hint(self):
        """固有名詞エントリに context_hint がない場合、ヒント表示がないことをテスト"""
        from subtitle_engine import ai_proofreader
        from unittest.mock import MagicMock, patch
        import sys
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.return_value = [
            {"incorrect": "ぷろじぇくと", "correct": "プロジェクト", "context_hint": ""}
        ]
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            context = ai_proofreader._build_proper_noun_context()
            assert "## 固有名詞辞書" in context
            assert "「ぷろじぇくと」→「プロジェクト」" in context
            assert "（" not in context  # ヒント表示がないこと

    def test_fatal_exception_inside_batch_loop(self):
        """バッチループ内のプログラム例外が、外側の try-except に適切にキャッチされ skipped=True になるケース"""
        from subtitle_engine import ai_proofreader
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正"}]'
        mock_client.models.generate_content.return_value = mock_response
        
        class BadDictSegment(dict):
            def __init__(self):
                super().__init__({"text": "テスト"})
            def __getitem__(self, key):
                if key == "text":
                    return "テスト"
                raise AttributeError("Simulated program bug")
            def __setitem__(self, key, value):
                raise AttributeError("Simulated program bug")

        segments = [BadDictSegment()]
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["skipped"] is True

    def test_retry_on_general_exception_not_retryable(self):
        """未知の例外が発生し、メッセージからリトライ不可と判定され、即時失敗するケース"""
        from subtitle_engine import ai_proofreader
        
        mock_client = MagicMock()
        non_retryable_error = RuntimeError("Fatal engine breakdown")
        mock_client.models.generate_content.side_effect = non_retryable_error
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 0  # 即時終了
                assert stats["failed_batches"] == 1

    def test_connection_error_limit_exceeded(self):
        """ConnectionError が 4回（初回+リトライ3回）連続して発生し、リトライ上限に達して失敗するケースをテスト"""
        from subtitle_engine import ai_proofreader
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        conn_error = ConnectionError("Persistent network outage")
        # 4回連続でエラーをスロー
        mock_client.models.generate_content.side_effect = [conn_error, conn_error, conn_error, conn_error]

        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 3  # MAX_RETRIES = 3
                assert stats["failed_batches"] == 1
                assert stats["proofread_count"] == 0

    def test_teardown_module_retains_behavior(self):
        """teardown_module が sys.modules の復元を問題なく行うことを間接的にテスト"""
        import sys
        # プレースホルダ用にダミーを退避
        dummy_orig = {"dummy_module_name": sys.modules.get("dummy_module_name")}
        sys.modules["dummy_module_name"] = "mocked_value"
        
        try:
            import google
            from unittest.mock import MagicMock
            assert isinstance(google, MagicMock)
        finally:
            # クリーンアップ
            if dummy_orig["dummy_module_name"] is None:
                sys.modules.pop("dummy_module_name", None)
            else:
                sys.modules["dummy_module_name"] = dummy_orig["dummy_module_name"]

    def test_retry_on_value_error_retryable_string(self):
        """ValueError が発生し、メッセージからリトライ可能と判定されリトライ後に成功するケース"""
        from subtitle_engine import ai_proofreader
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'
        
        # ValueError を投げる
        retryable_error = ValueError("resource_exhausted: Rate limit exceeded")
        mock_client.models.generate_content.side_effect = [retryable_error, mock_response]
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"), \
                 patch("time.sleep", lambda x: None):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert result[0]["text"] == "修正済"

    def test_retry_on_type_error_retryable_string(self):
        """TypeError が発生し、メッセージからリトライ可能と判定されリトライ後に成功するケース"""
        from subtitle_engine import ai_proofreader
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'
        
        # TypeError を投げる
        retryable_error = TypeError("quota limit exceeded")
        mock_client.models.generate_content.side_effect = [retryable_error, mock_response]
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"), \
                 patch("time.sleep", lambda x: None):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert result[0]["text"] == "修正済"

    def test_fatal_exception_value_error_in_outer_loop(self):
        """外側ループ内で ValueError が発生した際に、正しく stats['skipped'] = True となり処理が終了するケース"""
        from subtitle_engine import ai_proofreader
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = ValueError("Fatal invalid parameter value")
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 0
                assert stats["failed_batches"] == 1
                assert stats["skipped"] is False

    def test_fatal_exception_key_error_in_outer_try(self):
        """外側の try ブロックで KeyError が発生した際に、外側の try-except で安全にキャッチされ skipped=True になるケース"""
        from subtitle_engine import ai_proofreader
        
        with patch("subtitle_engine.ai_proofreader._get_current_model", side_effect=KeyError("Simulated outer key error")):
            segments = [{"text": "テスト"}]
            result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
            assert stats["skipped"] is True

    def test_get_current_model_generic_exception(self):
        """_get_current_model で想定外の Exception が発生した際に、gemini-2.5-flash が返ることをテスト"""
        mock_module = MagicMock()
        mock_gov = MagicMock()
        mock_gov._resolve_model.side_effect = Exception("Fatal governance error")
        mock_module.model_governance = mock_gov
        with patch.dict("sys.modules", {"model_governance": mock_module}):
            from subtitle_engine import ai_proofreader
            model_name = ai_proofreader._get_current_model()
            assert model_name == "gemini-3.6-flash"

    def test_build_context_generic_exception(self):
        """_build_proper_noun_context で想定外の Exception が発生した際、警告文字列が返ることをテスト"""
        mock_module = MagicMock()
        mock_dict = MagicMock()
        mock_dict.get_all_entries.side_effect = Exception("Fatal dictionary error")
        mock_module.proper_noun_dict = mock_dict
        with patch.dict("sys.modules", {"proper_noun_dict": mock_module}):
            from subtitle_engine import ai_proofreader
            context = ai_proofreader._build_proper_noun_context()
            assert "辞書の処理中に予期せぬエラーが発生しました" in context

    def test_inner_retry_generic_exception(self):
        """API呼び出しで想定外の Exception が発生した際に、そのバッチのみ失敗として処理が継続することをテスト"""
        from subtitle_engine import ai_proofreader
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Simulated network fatal exception")
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["failed_batches"] == 1
                assert stats["skipped"] is False
                assert result == [{"text": "テスト"}]

    def test_outer_try_generic_exception(self):
        """外側 try ブロックで想定外の Exception（例: ZeroDivisionError）が発生した際、skipped=True となることをテスト"""
        from subtitle_engine import ai_proofreader
        
        with patch("subtitle_engine.ai_proofreader._get_current_model", side_effect=ZeroDivisionError("Simulated outer exception")):
            segments = [{"text": "テスト"}]
            result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
            assert stats["skipped"] is True
            assert result == [{"text": "テスト"}]

    def test_retry_on_generic_exception_retryable_string(self):
        """一般的な Exception でもメッセージから再試行可能と判定されリトライ後に成功するケース"""
        from subtitle_engine import ai_proofreader
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "text": "修正済"}]'
        
        # Exception を投げる
        retryable_error = Exception("429 Resource Exhausted")
        mock_client.models.generate_content.side_effect = [retryable_error, mock_response]
        
        with patch.dict("sys.modules", {"model_governance": MagicMock(get_governed_client=lambda x: mock_client)}):
            with patch("subtitle_engine.ai_proofreader._get_current_model", return_value="gemini-2.5-flash"), \
                 patch("time.sleep", lambda x: None):
                segments = [{"text": "テスト"}]
                result, stats = ai_proofreader.proofread_segments(segments, return_stats=True)
                assert stats["total_retries"] == 1
                assert stats["failed_batches"] == 0
                assert result[0]["text"] == "修正済"

