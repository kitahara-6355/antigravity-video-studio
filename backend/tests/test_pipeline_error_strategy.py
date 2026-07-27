"""Tests for pipeline_error_strategy module.

4分類エラーハンドリング戦略（RETRY/FALLBACK/FATAL/DIAGNOSE）の
全関数・クラスを網羅的にテストする。
"""
import json
from unittest.mock import patch
from typing import Any

import pytest

from pipeline_error_strategy import (
    PipelineErrorStrategy,
    PipelineFatalError,
    QualityDegradation,
    _log_quality_degradation,
    pipeline_diagnose,
    pipeline_fallback,
    pipeline_retry,
    QUALITY_LOG_PATH,
    robust_retry,
    intelligent_fallback,
    healing_io_retry,
)
from backend.services.error_classifier import ErrorCategory, ClassificationResult, ErrorSeverity, ErrorAction


class TestPipelineErrorStrategyEnum:
    """PipelineErrorStrategy enumのテスト."""

    def test_enum_has_four_values(self) -> None:
        """4つの戦略値が存在すること."""
        assert PipelineErrorStrategy.RETRY.value == "retry"
        assert PipelineErrorStrategy.FALLBACK.value == "fallback"
        assert PipelineErrorStrategy.FATAL.value == "fatal"
        assert PipelineErrorStrategy.DIAGNOSE.value == "diagnose"
        assert len(PipelineErrorStrategy) == 4


class TestPipelineFatalError:
    """PipelineFatalErrorのテスト."""

    def test_fatal_error_exists_and_is_exception(self) -> None:
        """PipelineFatalErrorが存在しExceptionを継承すること."""
        err = PipelineFatalError("critical failure")
        assert isinstance(err, Exception)
        assert str(err) == "critical failure"


class TestQualityDegradation:
    """QualityDegradationのテスト."""

    def test_to_dict_contains_correct_keys(self) -> None:
        """to_dict()が正しいキーセットを含むこと."""
        deg = QualityDegradation(
            phase="subtitle",
            severity="minor",
            fallback_used="default font",
            original_error="FileNotFoundError: font.ttf",
        )
        result = deg.to_dict()
        expected_keys = {"phase", "severity", "fallback_used", "original_error", "timestamp"}
        assert set(result.keys()) == expected_keys
        assert result["phase"] == "subtitle"
        assert result["severity"] == "minor"
        assert result["fallback_used"] == "default font"
        assert result["original_error"] == "FileNotFoundError: font.ttf"
        # timestamp は ISO形式の文字列
        assert isinstance(result["timestamp"], str)
        assert "T" in result["timestamp"]


class TestPipelineRetry:
    """pipeline_retryのテスト."""

    def test_returns_result_on_success(self) -> None:
        """成功時に結果を返すこと."""
        result = pipeline_retry(lambda: 42, max_retries=3, backoff_base=0.0)
        assert result == 42

    def test_retries_and_raises_on_exhaustion(self) -> None:
        """全リトライ失敗時に最後の例外を上げること."""
        call_count = 0

        def failing_func() -> None:
            nonlocal call_count
            call_count += 1
            raise ValueError(f"fail #{call_count}")

        with pytest.raises(ValueError, match="fail #4"):
            pipeline_retry(failing_func, max_retries=3, backoff_base=0.0)

        # 初回 + リトライ3回 = 合計4回呼ばれる
        assert call_count == 4

    def test_retries_then_succeeds(self) -> None:
        """途中で成功した場合、その結果を返すこと."""
        attempts = []

        def eventually_succeeds() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("not yet")
            return "ok"

        result = pipeline_retry(eventually_succeeds, max_retries=5, backoff_base=0.0)
        assert result == "ok"
        assert len(attempts) == 3


class TestPipelineFallback:
    """pipeline_fallbackデコレータのテスト."""

    def test_returns_fallback_value_on_exception(self) -> None:
        """例外時にfallback_valueを返すこと."""
        @pipeline_fallback(
            phase="encoding",
            severity="moderate",
            fallback_value="default.mp4",
            fallback_desc="use default encoding",
        )
        def broken_encode() -> str:
            raise RuntimeError("encoder crashed")

        result = broken_encode()
        assert result == "default.mp4"

    def test_returns_normal_value_on_success(self) -> None:
        """正常時は元の戻り値を返すこと."""
        @pipeline_fallback(
            phase="encoding",
            severity="minor",
            fallback_value="fallback.mp4",
            fallback_desc="use fallback",
        )
        def good_encode() -> str:
            return "success.mp4"

        assert good_encode() == "success.mp4"

    def test_writes_quality_log(self, tmp_path: "Path") -> None:
        """品質低下ログがpipeline_quality_log.jsonlに書き込まれること."""
        log_path = tmp_path / "pipeline_quality_log.jsonl"

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            @pipeline_fallback(
                phase="thumbnail",
                severity="major",
                fallback_value=None,
                fallback_desc="skip thumbnail",
            )
            def broken_thumbnail() -> None:
                raise FileNotFoundError("image.png not found")

            broken_thumbnail()

        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["phase"] == "thumbnail"
        assert record["severity"] == "major"
        assert record["fallback_used"] == "skip thumbnail"
        assert "FileNotFoundError" in record["original_error"]


class TestPipelineDiagnose:
    """pipeline_diagnoseデコレータのテスト."""

    def test_returns_none_on_exception(self) -> None:
        """例外時にNoneを返して処理を続行すること."""
        @pipeline_diagnose
        def fragile_check() -> str:
            raise ConnectionError("network down")

        result = fragile_check()
        assert result is None

    def test_returns_normal_value_on_success(self) -> None:
        """正常時は元の戻り値を返すこと."""
        @pipeline_diagnose
        def healthy_check() -> int:
            return 200

        assert healthy_check() == 200


class TestLogQualityDegradation:
    """_log_quality_degradation内部関数のテスト."""

    def test_creates_log_file(self, tmp_path: "Path") -> None:
        """ログファイルが新規作成されること."""
        log_path = tmp_path / "subdir" / "quality.jsonl"

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            deg = QualityDegradation(
                phase="audio",
                severity="minor",
                fallback_used="mono fallback",
                original_error="StereoError: channels",
            )
            _log_quality_degradation(deg)

        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["phase"] == "audio"

    def test_appends_to_existing_log(self, tmp_path: "Path") -> None:
        """既存ログに追記されること."""
        log_path = tmp_path / "quality.jsonl"
        log_path.write_text('{"existing": true}\n', encoding="utf-8")

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            deg = QualityDegradation(
                phase="color",
                severity="moderate",
                fallback_used="default LUT",
                original_error="LUTError: missing",
            )
            _log_quality_degradation(deg)

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["existing"] is True
        assert json.loads(lines[1])["phase"] == "color"

    def test_log_quality_degradation_handles_os_error(self, tmp_path: "Path", caplog: pytest.LogCaptureFixture) -> None:
        """OSError発生時に例外をキャッチし、警告ログを出力すること."""
        log_path = tmp_path / "quality.jsonl"

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            deg = QualityDegradation(
                phase="audio",
                severity="minor",
                fallback_used="mono fallback",
                original_error="StereoError: channels",
            )
            with patch("builtins.open", side_effect=OSError("Disk full")):
                # 例外が投げられずに正常終了すること
                _log_quality_degradation(deg)

        # 警告ログの出力を確認
        assert any(
            "Failed to write quality degradation log" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )


class TestPrivateHelpers:
    """内部ヘルパー関数のテスト."""

    def test_calculate_backoff_seconds(self) -> None:
        """バックオフ待機時間が正しく計算されること."""
        from pipeline_error_strategy import _calculate_backoff_seconds
        assert _calculate_backoff_seconds(1.0, 0) == 1.0
        assert _calculate_backoff_seconds(1.0, 1) == 2.0
        assert _calculate_backoff_seconds(1.0, 2) == 4.0
        assert _calculate_backoff_seconds(2.5, 3) == 20.0

    def test_write_degradation_record(self, tmp_path: "Path") -> None:
        """レコードが正しくファイルに書き込まれること."""
        from pipeline_error_strategy import _write_degradation_record
        log_path = tmp_path / "degradation_test.jsonl"
        record = {"test_phase": "test", "status": "ok"}
        
        _write_degradation_record(log_path, record)
        assert log_path.exists()
        
        content = log_path.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        assert data == record


class TestRobustRetry:
    """robust_retryのテスト."""

    def test_robust_retry_success(self) -> None:
        """最初から成功する場合."""
        result = robust_retry(lambda: "success", max_retries=3, backoff_base=0.0)
        assert result == "success"

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_robust_retry_rate_limit_retry_success(self, mock_classify: Any, mock_sleep: Any) -> None:
        """API_RATE_LIMITでリトライして成功する場合."""
        exc = ValueError("rate limit")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.API_RATE_LIMIT,
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.RETRY,
            reason="Rate limit exceeded",
            original_exception=exc
        )
        calls = 0

        def failing_func() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exc
            return "ok"

        result = robust_retry(failing_func, max_retries=3, backoff_base=1.0)
        assert result == "ok"
        assert calls == 2
        # API_RATE_LIMITの場合は待機時間が2倍
        # attempt=0 の場合: _calculate_backoff_seconds(1.0, 0) * 2.0 = 1.0 * (2^0) * 2.0 = 2.0秒
        mock_sleep.assert_called_once_with(2.0)

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_robust_retry_timeout_retry_success(self, mock_classify: Any, mock_sleep: Any) -> None:
        """NETWORK_TIMEOUTでリトライして成功する場合."""
        exc = ValueError("timeout")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.NETWORK_TIMEOUT,
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.RETRY,
            reason="Timeout",
            original_exception=exc
        )
        calls = 0

        def failing_func() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exc
            return "ok"

        result = robust_retry(failing_func, max_retries=3, backoff_base=1.0)
        assert result == "ok"
        assert calls == 2
        # NETWORK_TIMEOUTの場合は待機時間が1倍
        # attempt=0 の場合: _calculate_backoff_seconds(1.0, 0) * 1.0 = 1.0 * (2^0) = 1.0秒
        mock_sleep.assert_called_once_with(1.0)

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_robust_retry_exhausted(self, mock_classify: Any, mock_sleep: Any) -> None:
        """リトライ上限を超えて失敗する場合."""
        exc = ValueError("always timeout")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.NETWORK_TIMEOUT,
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.RETRY,
            reason="Timeout",
            original_exception=exc
        )

        def failing_func() -> None:
            raise exc

        with pytest.raises(ValueError, match="always timeout"):
            robust_retry(failing_func, max_retries=2, backoff_base=1.0)

        # max_retries=2 の場合、attempt_indexは 0, 1, 2。
        # attempt_index = 0, 1 でリトライ (time.sleep が呼ばれる)
        # attempt_index = 2 で上限到達して raise
        assert mock_sleep.call_count == 2

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_robust_retry_unsupported_category(self, mock_classify: Any) -> None:
        """対象外のエラーカテゴリの場合は即座に再送出されること."""
        exc = TypeError("invalid type")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.DATA_CORRUPTION,  # 対象外
            severity=ErrorSeverity.MODERATE,
            action=ErrorAction.FALLBACK,
            reason="Data corruption",
            original_exception=exc
        )

        def failing_func() -> None:
            raise exc

        with pytest.raises(TypeError, match="invalid type"):
            robust_retry(failing_func, max_retries=3, backoff_base=1.0)


class TestIntelligentFallback:
    """intelligent_fallbackのテスト."""

    def test_intelligent_fallback_success(self) -> None:
        """最初から成功する場合."""
        @intelligent_fallback(phase="test", severity="minor", fallback_value="fb", fallback_desc="desc")
        def good_func() -> str:
            return "good"

        assert good_func() == "good"

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_intelligent_fallback_data_corruption_healing_success(self, mock_classify: Any) -> None:
        """DATA_CORRUPTIONでtemperatureが調整されて成功する場合."""
        exc = ValueError("json error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.DATA_CORRUPTION,
            severity=ErrorSeverity.MODERATE,
            action=ErrorAction.FALLBACK,
            reason="JSON broken",
            original_exception=exc
        )
        calls = []

        def heal_func(temperature: float = 0.7) -> str:
            calls.append(temperature)
            if temperature > 0.1:
                raise exc
            return "healed"

        decorated = intelligent_fallback(
            phase="test", severity="minor", fallback_value="fb", fallback_desc="desc"
        )(heal_func)

        result = decorated(temperature=0.7)
        assert result == "healed"
        assert calls == [0.7, 0.0]  # 初回0.7でエラー、2回目0.0で成功

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_intelligent_fallback_data_corruption_healing_fail(self, mock_classify: Any, tmp_path: "Path") -> None:
        """DATA_CORRUPTIONで再試行後も失敗し、フォールバック値を返す場合."""
        exc = ValueError("persistent json error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.DATA_CORRUPTION,
            severity=ErrorSeverity.MODERATE,
            action=ErrorAction.FALLBACK,
            reason="JSON broken",
            original_exception=exc
        )
        log_path = tmp_path / "quality.jsonl"

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            calls = []

            def bad_func(temp: float = 0.5) -> str:
                calls.append(temp)
                raise exc

            decorated = intelligent_fallback(
                phase="test_phase", severity="moderate", fallback_value="fb_val", fallback_desc="fb_desc"
            )(bad_func)

            result = decorated(temp=0.5)
            assert result == "fb_val"
            assert calls == [0.5, 0.0]

            assert log_path.exists()
            record = json.loads(log_path.read_text(encoding="utf-8").strip())
            assert record["phase"] == "test_phase"
            assert record["severity"] == "moderate"
            assert record["fallback_used"] == "fb_desc"
            assert "ValueError" in record["original_error"]

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_intelligent_fallback_data_corruption_no_temp(self, mock_classify: Any) -> None:
        """temperature引数がない場合でもDATA_CORRUPTIONで再試行され、失敗時にフォールバックされること."""
        exc = ValueError("no temp arg error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.DATA_CORRUPTION,
            severity=ErrorSeverity.MODERATE,
            action=ErrorAction.FALLBACK,
            reason="JSON broken",
            original_exception=exc
        )
        calls = 0

        def no_temp_func() -> str:
            nonlocal calls
            calls += 1
            raise exc

        decorated = intelligent_fallback(
            phase="test", severity="minor", fallback_value="fb", fallback_desc="desc"
        )(no_temp_func)

        result = decorated()
        assert result == "fb"
        assert calls == 2  # 初回 + temperature無しのまま再試行で合計2回

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_intelligent_fallback_unsupported_category(self, mock_classify: Any, tmp_path: "Path") -> None:
        """DATA_CORRUPTION以外のカテゴリでは再試行せず即座にフォールバックすること."""
        exc = ValueError("timeout error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.NETWORK_TIMEOUT,  # 対象外
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.RETRY,
            reason="Timeout",
            original_exception=exc
        )
        log_path = tmp_path / "quality.jsonl"

        with patch("pipeline_error_strategy.QUALITY_LOG_PATH", log_path):
            calls = 0

            def failing_func() -> str:
                nonlocal calls
                calls += 1
                raise exc

            decorated = intelligent_fallback(
                phase="test", severity="minor", fallback_value="fb_val", fallback_desc="desc"
            )(failing_func)

            result = decorated()
            assert result == "fb_val"
            assert calls == 1  # リトライせずに1回だけ実行


class TestHealingIoRetry:
    """healing_io_retryのテスト."""

    def test_healing_io_retry_success(self) -> None:
        """最初から成功する場合."""
        result = healing_io_retry(lambda: "success", max_retries=2)
        assert result == "success"

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    @patch("backend.agents.orchestration.cleanup_disk.main")
    def test_healing_io_retry_cleanup_success(self, mock_cleanup: Any, mock_classify: Any, mock_sleep: Any) -> None:
        """FILE_IO_ERRORでクリーンアップを伴いリトライ成功する場合."""
        exc = OSError("io error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.FILE_IO_ERROR,
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.CLEANUP_AND_RETRY,
            reason="Disk error",
            original_exception=exc
        )
        calls = 0

        def failing_func() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exc
            return "ok"

        result = healing_io_retry(failing_func, max_retries=2)
        assert result == "ok"
        assert calls == 2
        mock_cleanup.assert_called_once()
        mock_sleep.assert_called_once_with(1.0)

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    @patch("backend.agents.orchestration.cleanup_disk.main")
    def test_healing_io_retry_cleanup_exception_handling(self, mock_cleanup: Any, mock_classify: Any, mock_sleep: Any) -> None:
        """クリーンアップ実行時に例外が発生しても、それをキャッチしてリトライを続行すること."""
        exc = OSError("no space")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.RESOURCE_EXHAUSTED,
            severity=ErrorSeverity.CRITICAL,
            action=ErrorAction.CLEANUP_AND_RETRY,
            reason="No space left",
            original_exception=exc
        )
        mock_cleanup.side_effect = RuntimeError("Cleanup failed")
        calls = 0

        def failing_func() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exc
            return "ok"

        # cleanupが失敗しても、failing_func自体は2回目に成功するため、全体として成功する
        result = healing_io_retry(failing_func, max_retries=2)
        assert result == "ok"
        assert calls == 2
        mock_cleanup.assert_called_once()
        mock_sleep.assert_called_once_with(1.0)

    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    def test_healing_io_retry_unsupported_category(self, mock_classify: Any) -> None:
        """対象外のカテゴリの場合はリトライせずに即座に例外を発生させること."""
        exc = ValueError("timeout error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.NETWORK_TIMEOUT,  # 対象外
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.RETRY,
            reason="Timeout",
            original_exception=exc
        )

        def failing_func() -> None:
            raise exc

        with pytest.raises(ValueError, match="timeout error"):
            healing_io_retry(failing_func, max_retries=2)


class TestPipelineErrorStrategyExtra:
    """追加のテストケース（境界値、インポートパス、異常系モック）."""

    def test_sys_path_injection(self) -> None:
        """sys.path に _PROJECT_ROOT が含まれていない場合に再挿入されること."""
        import sys
        import importlib
        import pipeline_error_strategy
        from pathlib import Path

        project_root = Path(pipeline_error_strategy.__file__).resolve().parent.parent
        project_root_str = str(project_root)

        # 一時的に sys.path からプロジェクトルートを削除
        original_path = sys.path.copy()
        try:
            while project_root_str in sys.path:
                sys.path.remove(project_root_str)
            
            # 再ロードを実行
            importlib.reload(pipeline_error_strategy)
            
            # 再挿入されていることを確認
            assert sys.path[0] == project_root_str
        finally:
            sys.path = original_path

    def test_robust_retry_zero_retries(self) -> None:
        """robust_retry で max_retries が 0 の場合、最初の失敗で即座に再送出されること."""
        calls = 0
        def failing_func() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("rate limit error")

        with patch("pipeline_error_strategy.ErrorClassifier.classify") as mock_classify:
            mock_classify.return_value = ClassificationResult(
                category=ErrorCategory.API_RATE_LIMIT,
                severity=ErrorSeverity.MAJOR,
                action=ErrorAction.RETRY,
                reason="Rate limit",
                original_exception=ValueError("rate limit error")
            )
            with pytest.raises(ValueError, match="rate limit error"):
                robust_retry(failing_func, max_retries=0, backoff_base=0.0)
            
            assert calls == 1

    def test_intelligent_fallback_non_temperature_params(self) -> None:
        """intelligent_fallback で temperature/temp 以外の引数の場合は調整されないこと."""
        exc = ValueError("json broken")
        calls = []

        def dummy_func(param_a: str = "val") -> str:
            calls.append(param_a)
            raise exc

        with patch("pipeline_error_strategy.ErrorClassifier.classify") as mock_classify:
            mock_classify.return_value = ClassificationResult(
                category=ErrorCategory.DATA_CORRUPTION,
                severity=ErrorSeverity.MODERATE,
                action=ErrorAction.FALLBACK,
                reason="broken",
                original_exception=exc
            )
            decorated = intelligent_fallback(
                phase="test", severity="minor", fallback_value="fb", fallback_desc="desc"
            )(dummy_func)

            # temperature がない場合は引数がそのまま（再試行されるが param_a は "val" のまま）
            result = decorated(param_a="test_val")
            assert result == "fb"
            assert calls == ["test_val", "test_val"]

    @patch("pipeline_error_strategy.time.sleep")
    @patch("pipeline_error_strategy.ErrorClassifier.classify")
    @patch("backend.agents.orchestration.cleanup_disk.main")  # 本物の実行を完全に防ぐ
    def test_healing_io_retry_cleanup_import_error(self, mock_cleanup: Any, mock_classify: Any, mock_sleep: Any) -> None:
        """healing_io_retry で cleanup_disk のインポートが失敗した場合でも、エラーをキャッチしてリトライが継続されること."""
        exc = OSError("io error")
        mock_classify.return_value = ClassificationResult(
            category=ErrorCategory.FILE_IO_ERROR,
            severity=ErrorSeverity.MAJOR,
            action=ErrorAction.CLEANUP_AND_RETRY,
            reason="Disk error",
            original_exception=exc
        )
        calls = 0

        def failing_func() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise exc
            return "ok"

        # builtins.__import__ をモックして、cleanup_disk のインポート時に ImportError を発生させる
        import builtins
        import sys
        
        # パッケージオブジェクトから cleanup_disk 属性を一時的に退避してインポートエラーを強制する
        orchestration = sys.modules.get("backend.agents.orchestration")
        had_attribute = False
        original_attribute_val = None
        if orchestration and hasattr(orchestration, "cleanup_disk"):
            had_attribute = True
            original_attribute_val = orchestration.cleanup_disk
            delattr(orchestration, "cleanup_disk")

        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "cleanup_disk" in name:
                raise ImportError("mocked import error")
            return original_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=mock_import):
                result = healing_io_retry(failing_func, max_retries=2)
                assert result == "ok"
                assert calls == 2
        finally:
            # テスト完了後にパッケージの属性を元に戻す
            if had_attribute and orchestration:
                setattr(orchestration, "cleanup_disk", original_attribute_val)



