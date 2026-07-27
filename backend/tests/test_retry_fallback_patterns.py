import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# プロジェクトルートを追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.pipeline_error_strategy import robust_retry, intelligent_fallback, healing_io_retry
from backend.services.error_classifier import ErrorCategory

# --- パターン1: robust_retry のテスト ---

def test_robust_retry_success_after_failure():
    attempts = 0
    def mock_api_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception("API rate limit exceeded: status_code=429")
        return "success"

    # backoff_base=0.01 にしてテストを高速化
    result = robust_retry(mock_api_call, max_retries=3, backoff_base=0.01)
    
    assert result == "success"
    assert attempts == 3

def test_robust_retry_immediate_failure_for_unsupported_error():
    attempts = 0
    def mock_bad_call():
        nonlocal attempts
        attempts += 1
        raise ValueError("Fatal value error")

    with pytest.raises(ValueError) as excinfo:
        robust_retry(mock_bad_call, max_retries=3, backoff_base=0.01)
        
    assert "Fatal value error" in str(excinfo.value)
    # リトライ対象外なので、リトライされずに1回目の呼び出しで終了するはず
    assert attempts == 1


# --- パターン2: intelligent_fallback のテスト ---

def test_intelligent_fallback_parameter_adjustment():
    attempts = 0
    
    # DATA_CORRUPTION（JSONパース失敗）を投げるが、
    # temperature が 0.0 の場合は成功する関数
    def mock_llm_call(temperature=0.7):
        nonlocal attempts
        attempts += 1
        if temperature > 0.0:
            raise Exception("JSONDecodeError: Failed to parse model output")
        return "healed_success"

    # デコレータを適用
    decorated_func = intelligent_fallback(
        phase="test_phase",
        severity="moderate",
        fallback_value="fallback_val",
        fallback_desc="LLM fallback"
    )(mock_llm_call)

    # temperature=0.7 で呼び出し
    result = decorated_func(temperature=0.7)
    
    assert result == "healed_success"
    assert attempts == 2  # 1回目は失敗し、修復パラメータ（temperature=0.0）で2回目が呼び出されて成功

def test_intelligent_fallback_to_default_value():
    # 常に失敗する関数
    def mock_always_fail(temperature=0.7):
        raise Exception("JSONDecodeError: Permanent failure")

    decorated_func = intelligent_fallback(
        phase="test_phase",
        severity="moderate",
        fallback_value="fallback_val",
        fallback_desc="LLM fallback"
    )(mock_always_fail)

    result = decorated_func(temperature=0.7)
    
    assert result == "fallback_val"


# --- パターン3: healing_io_retry のテスト ---

@patch("backend.agents.orchestration.cleanup_disk.main")
def test_healing_io_retry_trigger_cleanup(mock_cleanup):
    attempts = 0
    def mock_file_write():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise OSError("[Errno 28] No space left on device")
        return "write_success"

    result = healing_io_retry(mock_file_write, max_retries=2)
    
    assert result == "write_success"
    assert attempts == 2
    mock_cleanup.assert_called_once()  # 1回目の失敗時にクリーンアップが走ったことを確認
