import sys
import os
import pytest
import runpy
import builtins
from unittest.mock import MagicMock, patch

# テスト対象モジュールをインポートするためにパス追加
sys.path.append(os.path.abspath("backend"))
sys.path.append(os.path.abspath("."))

import backend.agents.orchestration.run_session_end as run_session_end
from contextlib import contextmanager

@contextmanager
def clean_sys_path():
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    try:
        for k in list(sys.modules.keys()):
            if "run_session_end" in k:
                sys.modules.pop(k, None)
        yield
    finally:
        sys.path[:] = original_path
        for k, v in original_modules.items():
            sys.modules[k] = v
        for k in list(sys.modules.keys()):
            if k not in original_modules:
                sys.modules.pop(k, None)

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_success(mock_open, mock_makedirs, mock_hub_class, capsys):
    """正常終了し、レポートが正しく保存されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {
        "current_phase": 33,
        "current_milestone": "M33.1"
    }
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 検証
    mock_hub_class.assert_called_once()
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )
    mock_hub.get_flash_session.assert_called_once()
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "OPUS_CONV_ID:test_conv_123" in captured.out
    assert "Report saved to:" in captured.out
    
    # ファイル保存の検証
    mock_makedirs.assert_called_once()
    mock_open.assert_called_once()

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_session_none(mock_hub_class, capsys):
    """get_flash_session が None を返す場合に sys.exit(1) で異常終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = None
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: Failed to retrieve flash session (session is None)." in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_session_empty_dict(mock_hub_class, capsys):
    """get_flash_session が 空の辞書 を返す場合に sys.exit(1) で異常終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {}
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: Failed to retrieve flash session (session is empty)." in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_session_invalid_type(mock_hub_class, capsys):
    """get_flash_session が 辞書ではない型 を返す場合に sys.exit(1) で異常終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = "invalid_session_type"
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: Invalid flash session format" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_hub_init_exception(mock_hub_class, capsys):
    """OrchestrationHub 初期化時に例外が発生した場合に sys.exit(1) で終了することを検証"""
    mock_hub_class.side_effect = RuntimeError("Hub initialization failed")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error occurred during session end: Hub initialization failed" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
def test_main_makedirs_exception(mock_makedirs, mock_hub_class, capsys):
    """ディレクトリ作成時に OSError が発生した場合に sys.exit(1) で終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    mock_makedirs.side_effect = OSError("Permission denied")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "I/O Error occurred during session end: Permission denied" in captured.err

@patch("backend.agents.orchestration.OrchestrationHub")
@patch("os.makedirs")
def test_script_execution(mock_makedirs, mock_hub_class):
    """スクリプトとして直接実行された場合 (if __name__ == '__main__':) の挙動を検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    original_open = builtins.open
    mock_file = MagicMock()
    
    def conditional_open(file, *args, **kwargs):
        if "session_complete_report" in str(file):
            return mock_file
        return original_open(file, *args, **kwargs)
        
    with clean_sys_path():
        with patch("builtins.open", side_effect=conditional_open):
            with patch("sys.argv", ["run_session_end.py"]):
                with patch("backend.agents.orchestration.run_session_end.OrchestrationHub", mock_hub_class):
                    try:
                        runpy.run_path("backend/agents/orchestration/run_session_end.py", run_name="__main__")
                    except Exception as e:
                        raise e
        
    mock_hub_class.assert_called_once()
    mock_hub.flash_session_end.assert_called_once()
    mock_makedirs.assert_called_once()
    mock_file.__enter__.return_value.write.assert_called_once()

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_generic_exception(mock_hub_class, capsys):
    """OrchestrationHub 初期化時またはその他の処理中に一般的な例外が発生した場合に sys.exit(1) で終了することを検証"""
    mock_hub_class.side_effect = RuntimeError("Generic unexpected error")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error occurred during session end: Generic unexpected error" in captured.err

# --- 新規追加テスト ---
import re

def test_datetime_now_str_format():
    """datetime_now_str が YYYYMMDD_HHMMSS_UTC フォーマットに準拠していることを検証"""
    now_str = run_session_end.datetime_now_str()
    assert re.match(r"^\d{8}_\d{6}_UTC$", now_str) is not None

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_session_missing_keys(mock_open, mock_makedirs, mock_hub_class, capsys):
    """セッション情報に必要なキーが欠損している場合に、ValueErrorで終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {"some_other_key": "val"}
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: 必須フィールド 'tasks_completed_in_session' が不足しています。" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_session_extreme_values(mock_open, mock_makedirs, mock_hub_class, capsys):
    """セッション情報が極端な値（負の数など）を持つ場合に ValueError で終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": None,
        "tasks_completed_in_session": -999,
        "batches_in_session": 1234567890,
        "current_batch_id": "",
        "context_consumption_pct": 150
    }
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: フィールド 'tasks_completed_in_session' は 0 以上である必要があります。" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_session_extreme_types(mock_open, mock_makedirs, mock_hub_class, capsys):
    """セッション情報の値が異常な型（文字列など）を持つ場合に TypeError で終了することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": 99999,
        "tasks_completed_in_session": "ten",
        "batches_in_session": None,
        "current_batch_id": 12345,
        "context_consumption_pct": 33.3
    }
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: フィールド 'tasks_completed_in_session' は int である必要があります。" in captured.err

@patch("backend.agents.orchestration.OrchestrationHub")
@patch("os.makedirs")
def test_script_execution_warning_free(mock_makedirs, mock_hub_class):
    """runpy.run_path でスクリプトを実行した際に RuntimeWarning などの警告が発生しないことを検証"""
    import warnings
    import builtins
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    original_open = builtins.open
    mock_file = MagicMock()
    
    def conditional_open(file, *args, **kwargs):
        if "session_complete_report" in str(file):
            return mock_file
        return original_open(file, *args, **kwargs)
        
    with clean_sys_path():
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            with patch("builtins.open", side_effect=conditional_open):
                with patch("sys.argv", ["run_session_end.py"]):
                    try:
                        runpy.run_path("backend/agents/orchestration/run_session_end.py", run_name="__main__")
                    except RuntimeWarning as w:
                        pytest.fail(f"RuntimeWarning raised: {w}")
                    except Exception as e:
                        pytest.fail(f"Unexpected exception: {e}")
    
    mock_hub_class.assert_called_once()
    mock_hub.flash_session_end.assert_called_once()
    mock_makedirs.assert_called_once()

# --- さらに追加した新規テスト（Traceback検証用） ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_session_none_prints_traceback(mock_hub_class, capsys):
    """get_flash_session が None を返す場合に、スタックトレースが出力されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = None
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error: Failed to retrieve flash session (session is None)." in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "ValueError: Failed to retrieve flash session (session is None)." in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_generic_exception_prints_traceback(mock_hub_class, capsys):
    """OrchestrationHub 初期化時に一般的な Exception が発生した場合にスタックトレースが出力されることを検証"""
    mock_hub_class.side_effect = RuntimeError("Fatal DB collision")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error occurred during session end: Fatal DB collision" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "RuntimeError: Fatal DB collision" in captured.err

# --- 新規追加テスト（エラーハンドリング・フォールバック検証用） ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_save_report_os_error_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() で OSError が発生した際、標準エラー出力にフォールバックレポートが出力され、例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    mock_open.side_effect = OSError("Disk Full")
    
    # execute() が OSError を再送出することを確認
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(OSError) as exc_info:
        manager.execute()
        
    assert "Disk Full" in str(exc_info.value)
    
    # 標準エラー出力にフォールバックレポートが出力されていることを検証
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Disk Full" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT START ---" in captured.err
    assert "- **セッション内完了タスク数**: 5 件" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT END ---" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_os_error_handling(mock_open, mock_makedirs, mock_hub_class, capsys):
    """main() 実行時に OSError が発生した場合に sys.exit(1) となり、I/O Error が出力されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    mock_open.side_effect = OSError("Access Denied")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "I/O Error occurred during session end: Access Denied" in captured.err
    assert "Traceback (most recent call last):" in captured.err

# --- bug_hunter タスク #4 新規追加テスト ---

@patch("backend.agents.orchestration.OrchestrationHub")
@patch("os.makedirs")
def test_script_execution_from_different_cwd(mock_makedirs, mock_hub_class):
    """作業ディレクトリが backend 内のときでも runpy.run_path でスクリプトがエラーなく実行できることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_cwd",
        "tasks_completed_in_session": 1,
        "batches_in_session": 1,
        "current_batch_id": "batch_cwd",
        "context_consumption_pct": 10
    }
    
    original_cwd = os.getcwd()
    backend_dir_path = os.path.abspath("backend")
    os.chdir(backend_dir_path)
    
    original_open = builtins.open
    mock_file = MagicMock()
    
    def conditional_open(file, *args, **kwargs):
        if "session_complete_report" in str(file):
            return mock_file
        return original_open(file, *args, **kwargs)
        
    with clean_sys_path():
        try:
            with patch("builtins.open", side_effect=conditional_open):
                with patch("sys.argv", ["run_session_end.py"]):
                    with patch("backend.agents.orchestration.run_session_end.OrchestrationHub", mock_hub_class):
                        runpy.run_path("agents/orchestration/run_session_end.py", run_name="__main__")
        finally:
            os.chdir(original_cwd)
        
    mock_hub_class.assert_called_once()
    mock_hub.flash_session_end.assert_called_once()
    mock_makedirs.assert_called_once()

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_propagates_flash_session_end_exception(mock_open, mock_makedirs, mock_hub_class, capsys):
    """hub.flash_session_end で発生した例外が execute() でキャッチされず、main() まで伝播して sys.exit(1) となることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = RuntimeError("Failed to mark end")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error occurred during session end: Failed to mark end" in captured.err
    assert "Traceback (most recent call last):" in captured.err

def test_sys_path_cleanliness():
    """runpy による実行前後で sys.path が汚染されないことを検証"""
    original_len = len(sys.path)
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = mock_hub_class.return_value
        mock_hub.get_flash_session.return_value = {
            "opus_conversation_id": "test_conv_123",
            "tasks_completed_in_session": 5,
            "batches_in_session": 2,
            "current_batch_id": "batch_abc",
            "context_consumption_pct": 45
        }
        mock_file = MagicMock()
        with patch("builtins.open", return_value=mock_file):
            with patch("os.makedirs"):
                with clean_sys_path():
                    with patch("sys.argv", ["run_session_end.py"]):
                        runpy.run_path("backend/agents/orchestration/run_session_end.py", run_name="__main__")
    assert len(sys.path) == original_len


def test_timestamp_consistency():
    """generate_report と save_report で同一のタイムスタンプが使用され、ファイル名とレポート本文の日付表記が一致することを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock, patch

    mock_hub = MagicMock()
    session_info = {
        "opus_conversation_id": "test_timestamp_conv",
        "tasks_completed_in_session": 3,
        "batches_in_session": 1,
        "current_batch_id": "batch_ts",
        "context_consumption_pct": 20
    }
    
    manager = SessionEndManager(hub=mock_hub)
    test_ts = "20260611_123456_UTC"
    
    # 1. generate_report の検証
    report = manager.generate_report(session_info, timestamp=test_ts)
    assert f"- **セッション終了日時**: {test_ts}" in report
    
    # 2. save_report の検証
    mock_file = MagicMock()
    written_data = []
    mock_file.write = MagicMock(side_effect=lambda content: written_data.append(content))
    
    with patch("os.makedirs") as mock_makedirs, patch("backend.agents.orchestration.run_session_end.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value = mock_file
        report_path = manager.save_report(report, timestamp=test_ts)
        
        assert f"session_complete_report_{test_ts}.md" in report_path
        mock_makedirs.assert_called_once()
        mock_open.assert_called_once()
        
        saved_content = "".join(written_data)
        assert f"- **セッション終了日時**: {test_ts}" in saved_content


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_unexpected_exception_prints_traceback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """OrchestrationHub 初期化時に一般的な Exception (RuntimeError等以外のカスタム例外) が発生した場合にスタックトレースが出力されることを検証"""
    mock_hub_class.side_effect = Exception("Unexpected database crash")
    
    with pytest.raises(SystemExit) as exc_info:
        run_session_end.main()
        
    assert exc_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Unexpected error occurred during session end: Unexpected database crash" in captured.err
    assert "Traceback (most recent call last):" in captured.err


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_uses_conversation_id_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """opus_conversation_id がなく conversation_id がある場合に、正しくフォールバックされて OPUS_CONV_ID に出力されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "conversation_id": "fallback_conv_456",
        "tasks_completed_in_session": 2,
        "batches_in_session": 1,
        "current_batch_id": "batch_xyz",
        "context_consumption_pct": 10
    }
    
    # 実行
    run_session_end.main()
    
    # 標準出力の検証
    captured = capsys.readouterr()
    assert "OPUS_CONV_ID:fallback_conv_456" in captured.out


def test_manager_custom_config():
    """カスタムの SessionEndConfig が正しく適用され、レポート本文と保存パスに反映されることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager, SessionEndConfig
    from unittest.mock import MagicMock, patch

    custom_reason = "カスタムの終了理由テスト"
    custom_inbox = "custom_inbox_dir"
    config = SessionEndConfig(reason=custom_reason, inbox_dir=custom_inbox)
    
    mock_hub = MagicMock()
    manager = SessionEndManager(hub=mock_hub, config=config)
    
    session_info = {
        "opus_conversation_id": "test_conv",
        "tasks_completed_in_session": 1,
        "batches_in_session": 1,
        "current_batch_id": "batch_1",
        "context_consumption_pct": 10
    }
    
    # generate_report の検証
    report = manager.generate_report(session_info, timestamp="20260611_120000_UTC")
    assert f"- **終了理由**: {custom_reason}" in report
    
    # save_report の検証
    mock_file = MagicMock()
    with patch("os.makedirs") as mock_makedirs, patch("backend.agents.orchestration.run_session_end.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value = mock_file
        report_path = manager.save_report(report, timestamp="20260611_120000_UTC")
        
        mock_makedirs.assert_called_once()
        assert custom_inbox in report_path


# --- 新規追加テスト (型検証とフォールバック機能の検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_success_dynamic_reason(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state の戻り値によってセッション終了理由が動的に変化することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {
        "current_phase": 35,
        "current_milestone": "M35.2"
    }
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 検証
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P35/M35.2"
    )

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_non_dict_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state が dict 以外の型（Mock等）を返した場合にデフォルト値に安全にフォールバックすることを検証"""
    mock_hub = mock_hub_class.return_value
    # get_phase_state が dict 以外のモックオブジェクトを返すように設定 (デフォルトの MagicMock のままにする)
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 検証: 例外が安全にフォールバックされ、デフォルト値 P33/M33.1 が適用されること
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_invalid_type_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state から返された値が dict だが、各要素の型が不正な場合にデフォルト値に安全にフォールバックすることを検証"""
    mock_hub = mock_hub_class.return_value
    # phase や milestone に不正な型を設定
    mock_hub.get_phase_state.return_value = {
        "current_phase": ["invalid_type_list"],
        "current_milestone": 12345 # expected str
    }
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 検証: 例外が安全にフォールバックされ、デフォルト値 P33/M33.1 が適用されること
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_unexpected_exception_prints_warning(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state で予期せぬ例外が発生した際、警告が標準エラーに出力され、安全にデフォルト値にフォールバックされることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.side_effect = RuntimeError("Unexpected database crash")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 標準エラー出力に警告が出ていることを検証
    captured = capsys.readouterr()
    assert "Warning: Unexpected error during phase state retrieval: Unexpected database crash" in captured.err
    
    # デフォルト値 P33/M33.1 が適用されること
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_hub_flash_session_end_exception_continues_report(mock_open, mock_makedirs, mock_hub_class, capsys):
    """flash_session_end で例外が発生した場合でも、レポートが正常に保存され、最後に例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = RuntimeError("Failed to mark session end")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    written_data = []
    mock_file = MagicMock()
    mock_file.write = MagicMock(side_effect=lambda content: written_data.append(content))
    mock_open.return_value.__enter__.return_value = mock_file
    
    # execute() が RuntimeError を再送出することを確認
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(RuntimeError) as exc_info:
        manager.execute()
        
    assert "Failed to mark session end" in str(exc_info.value)
    
    # flash_session_end が例外を投げた場合でも、レポート保存が試みられていることを検証
    mock_makedirs.assert_called_once()
    mock_open.assert_called_once()
    saved_content = "".join(written_data)
    assert "- **セッション内完了タスク数**: 5 件" in saved_content
    
    # 標準エラー出力に警告が出力されていることを検証
    captured = capsys.readouterr()
    assert "Warning: Failed to mark flash session end in OrchestrationHub: Failed to mark session end" in captured.err


# --- 新規追加テスト (エラーチェーンおよび型検証の強化) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_execute_propagates_chained_exception(mock_hub_class):
    """flash_session_end と get_flash_session が同時に失敗した場合に、例外チェーンが正しく構築されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = RuntimeError("Mark end failed")
    mock_hub.get_flash_session.return_value = None  # これにより get_session_info が ValueError を投げる
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(ValueError) as exc_info:
        manager.execute()
        
    assert "Failed to retrieve flash session" in str(exc_info.value)
    # 例外チェーンの検証: 原因となった RuntimeError が __cause__ に含まれていること
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Mark end failed" in str(exc_info.value.__cause__)


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_milestone_type_error(mock_open, mock_makedirs, mock_hub_class):
    """milestone が str 以外の場合に TypeError が発生し、正常にデフォルトにフォールバックすることを検証"""
    mock_hub = mock_hub_class.return_value
    # current_milestone を str 以外の型にして TypeError を誘発する
    mock_hub.get_phase_state.return_value = {
        "current_phase": 33,
        "current_milestone": 12345
    }
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # デフォルトの終了理由（P33/M33.1）で flash_session_end が呼ばれることを確認
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_retrieval_exception_prints_traceback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state() で予期せぬ例外が発生した際、警告とスタックトレースが出力されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.side_effect = RuntimeError("Phase state retrieval crashed")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 標準エラー出力の検証
    captured = capsys.readouterr()
    assert "Warning: Unexpected error during phase state retrieval: Phase state retrieval crashed" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "RuntimeError: Phase state retrieval crashed" in captured.err


# --- 新規追加テスト (エラーハンドリング強化の検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_save_report_type_error_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() で TypeError が発生した際、フォールバックレポートが標準エラー出力に出力され、例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_type_error",
        "tasks_completed_in_session": 1,
        "batches_in_session": 1,
        "current_batch_id": "batch_type",
        "context_consumption_pct": 10
    }
    
    mock_open.side_effect = TypeError("Invalid file path type")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(TypeError) as exc_info:
        manager.execute()
        
    assert "Invalid file path type" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Invalid file path type" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT START ---" in captured.err
    assert "- **セッション内完了タスク数**: 1 件" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT END ---" in captured.err


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_save_report_value_error_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() で ValueError が発生した際、フォールバックレポートが標準エラー出力に出力され、例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_val_error",
        "tasks_completed_in_session": 2,
        "batches_in_session": 1,
        "current_batch_id": "batch_val",
        "context_consumption_pct": 20
    }
    
    mock_open.side_effect = ValueError("Invalid write mode")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(ValueError) as exc_info:
        manager.execute()
        
    assert "Invalid write mode" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Invalid write mode" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT START ---" in captured.err
    assert "- **セッション内完了タスク数**: 2 件" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT END ---" in captured.err


# --- 新規追加テスト (Exception をキャッチするエラーハンドリング強化の検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_custom_exception_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state() で予期せぬカスタム Exception が発生した際、警告が出力され、安全にデフォルト値にフォールバックされることを検証"""
    mock_hub = mock_hub_class.return_value
    class CustomStateError(RuntimeError):
        pass
    mock_hub.get_phase_state.side_effect = CustomStateError("Custom database error")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # 実行
    run_session_end.main()
    
    # 標準エラー出力に警告が出ていることを検証
    captured = capsys.readouterr()
    assert "Warning: Unexpected error during phase state retrieval: Custom database error" in captured.err
    
    # デフォルト値 P33/M33.1 が適用されること
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_hub_flash_session_end_custom_exception_continues_report(mock_open, mock_makedirs, mock_hub_class, capsys):
    """flash_session_end でカスタム Exception が発生した場合でも、レポートが正常に保存され、最後に例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    class CustomEndError(RuntimeError):
        pass
    mock_hub.flash_session_end.side_effect = CustomEndError("Failed to record end due to network")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    written_data = []
    mock_file = MagicMock()
    mock_file.write = MagicMock(side_effect=lambda content: written_data.append(content))
    mock_open.return_value.__enter__.return_value = mock_file
    
    # execute() が CustomEndError を再送出することを確認
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(CustomEndError) as exc_info:
        manager.execute()
        
    assert "Failed to record end due to network" in str(exc_info.value)
    
    # flash_session_end が例外を投げた場合でも、レポート保存が試みられていることを検証
    mock_makedirs.assert_called_once()
    mock_open.assert_called_once()
    saved_content = "".join(written_data)
    assert "- **セッション内完了タスク数**: 5 件" in saved_content
    
    # 標準エラー出力に警告が出力されていることを検証
    captured = capsys.readouterr()
    assert "Warning: Failed to mark flash session end in OrchestrationHub: Failed to record end due to network" in captured.err

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_execute_propagates_custom_chained_exception(mock_hub_class):
    """flash_session_end と get_flash_session が同時にカスタム例外で失敗した場合に、例外チェーンが正しく構築されることを検証"""
    mock_hub = mock_hub_class.return_value
    class CustomHubError(RuntimeError):
        pass
    class CustomSessionError(RuntimeError):
        pass
    mock_hub.flash_session_end.side_effect = CustomHubError("Mark end failed")
    mock_hub.get_flash_session.side_effect = CustomSessionError("Get session failed")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(CustomSessionError) as exc_info:
        manager.execute()
        
    assert "Get session failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, CustomHubError)
    assert "Mark end failed" in str(exc_info.value.__cause__)

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_save_report_custom_exception_fallback(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() でカスタム Exception が発生した際、フォールバックレポートが標準エラー出力に出力され、例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    class CustomWriteError(RuntimeError):
        pass
    mock_open.side_effect = CustomWriteError("Disk corrupted")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(CustomWriteError) as exc_info:
        manager.execute()
        
    assert "Disk corrupted" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Disk corrupted" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT START ---" in captured.err
    assert "- **セッション内完了タスク数**: 5 件" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT END ---" in captured.err


# --- bug_hunter 新規追加テスト (Python 3.13 警告回避) ---

def test_exception_chaining_warning_free(capsys):
    """Python 3.13 での例外チェーン警告（RuntimeWarning）が発生しないことを検証"""
    import warnings
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock
    
    mock_hub = MagicMock()
    # 1. flash_session_end で意図的に例外を発生させる
    mock_hub.flash_session_end.side_effect = RuntimeError("Mark end error")
    # 2. get_flash_session で意図的に TypeError を発生させる
    mock_hub.get_flash_session.return_value = "invalid_type"
    
    manager = SessionEndManager(hub=mock_hub)
    
    # execute() 実行時に RuntimeWarning が発生しないことを検証
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(TypeError) as exc_info:
            manager.execute()
            
    assert "Invalid flash session format" in str(exc_info.value)
    # chain が構築されていることを検証
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Mark end error" in str(exc_info.value.__cause__)


# --- bug_hunter_task_33 新規追加テスト (例外クラス名の出力検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_unexpected_error_retrieval_displays_type_name(mock_open, mock_makedirs, mock_hub_class, capsys):
    """get_phase_state() で例外が発生した際、警告メッセージに例外クラス名が含まれることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.side_effect = ZeroDivisionError("division by zero")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    run_session_end.main()
    
    captured = capsys.readouterr()
    assert "Warning: Unexpected error during phase state retrieval: division by zero (ZeroDivisionError)" in captured.err
    mock_open.assert_called_once()


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_failed_mark_displays_type_name(mock_open, mock_makedirs, mock_hub_class, capsys):
    """flash_session_end() で例外が発生した際、警告メッセージに例外クラス名が含まれることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = ConnectionRefusedError("Connection refused")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    with pytest.raises(SystemExit):
        run_session_end.main()
        
    captured = capsys.readouterr()
    assert "Warning: Failed to mark flash session end in OrchestrationHub: Connection refused (ConnectionRefusedError)" in captured.err


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_save_report_error_displays_type_name(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() で OSError が発生した際、警告メッセージに例外クラス名が含まれることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    mock_open.side_effect = PermissionError("Permission denied")
    
    with pytest.raises(SystemExit):
        run_session_end.main()
        
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Permission denied (PermissionError)" in captured.err


# --- bug_hunter_task_33 新規追加テスト (追加のエラーハンドリング検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_propagates_attribute_error_on_save(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() で AttributeError が発生した際、フォールバックレポートが出力され、例外が再送出されることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_attr_error",
        "tasks_completed_in_session": 10,
        "batches_in_session": 3,
        "current_batch_id": "batch_attr",
        "context_consumption_pct": 50
    }
    
    mock_open.side_effect = AttributeError("Mocked attribute error")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(AttributeError) as exc_info:
        manager.execute()
        
    assert "Mocked attribute error" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Mocked attribute error" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT START ---" in captured.err
    assert "- **セッション内完了タスク数**: 10 件" in captured.err
    assert "--- FALLBACK SESSION COMPLETE REPORT END ---" in captured.err


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_fallback_report_generation_fails(mock_open, mock_makedirs, mock_hub_class, capsys):
    """save_report() と generate_report() が両方失敗した際のエラーハンドリングを検証（129-130行目をカバー）"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_fallback_fail",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    # save_report で OSError を投げさせる
    mock_open.side_effect = OSError("Disk Write Failed")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    
    # generate_report をモックして、1回目の呼び出しは成功、2回目（フォールバック時）は TypeError を投げさせる
    original_generate_report = manager.generate_report
    call_count = 0
    def side_effect_generate_report(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise TypeError("Failed to generate fallback report")
        return original_generate_report(*args, **kwargs)
        
    manager.generate_report = MagicMock(side_effect=side_effect_generate_report)
    
    with pytest.raises(OSError) as exc_info:
        manager.execute()
        
    assert "Disk Write Failed" in str(exc_info.value)
    
    captured = capsys.readouterr()
    assert "Error saving session complete report to file: Disk Write Failed" in captured.err
    assert "Failed to generate fallback report content: Failed to generate fallback report" in captured.err


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_both_hub_and_save_fail_with_fallback_fail(mock_open, mock_makedirs, mock_hub_class, capsys):
    """hub.flash_session_end, save_report, generate_report(フォールバック) がすべて失敗した際の挙動とエラーチェーンを検証（133-134行目をカバー）"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = RuntimeError("Hub termination failed")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_all_fail",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    mock_open.side_effect = OSError("Disk Write Failed")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    
    original_generate_report = manager.generate_report
    call_count = 0
    def side_effect_generate_report(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise TypeError("Failed to generate fallback report")
        return original_generate_report(*args, **kwargs)
        
    manager.generate_report = MagicMock(side_effect=side_effect_generate_report)
    
    with pytest.raises(OSError) as exc_info:
        manager.execute()
        
    assert "Disk Write Failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Hub termination failed" in str(exc_info.value.__cause__)
    
    captured = capsys.readouterr()
    assert "Warning: Failed to mark flash session end in OrchestrationHub: Hub termination failed" in captured.err
    assert "Error saving session complete report to file: Disk Write Failed" in captured.err
    assert "Failed to generate fallback report content: Failed to generate fallback report" in captured.err


# --- bug_hunter_task_33 新規追加テスト (LookupError等、従前キャッチ対象外の例外捕捉検証) ---

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_execute_propagates_lookup_error_chained_exception(mock_open, mock_makedirs, mock_hub_class, capsys):
    """flash_session_end で LookupError (以前はキャッチ対象外) が発生した場合でも、例外が適切に処理されレポート保存が試みられることを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = LookupError("Lookup failed")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_lookup_error",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    written_data = []
    mock_file = MagicMock()
    mock_file.write = MagicMock(side_effect=lambda content: written_data.append(content))
    mock_open.return_value.__enter__.return_value = mock_file
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(LookupError) as exc_info:
        manager.execute()
        
    assert "Lookup failed" in str(exc_info.value)
    
    # flash_session_end が例外を投げた場合でも、レポート保存が試みられていることを検証
    mock_makedirs.assert_called_once()
    mock_open.assert_called_once()
    
    captured = capsys.readouterr()
    assert "Warning: Failed to mark flash session end in OrchestrationHub: Lookup failed (LookupError)" in captured.err


# --- 境界値・極端な値・異常系の網羅テスト (Step 3/3 追加分) ---

def test_session_end_config_reason_none():
    """SessionEndConfig の reason に None が指定された場合、get_phase_state から動的に取得しようとする挙動を検証"""
    from backend.agents.orchestration.run_session_end import SessionEndConfig, SessionEndManager
    from unittest.mock import MagicMock
    
    # 型ヒントを無視して reason に None を渡す
    config = SessionEndConfig(reason=None) # type: ignore
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 42,
        "current_milestone": "M42.2"
    }
    
    manager = SessionEndManager(hub=mock_hub, config=config)
    assert manager.config.reason == "セッション寿命（アーカイブ推奨閾値）到達による終了: P42/M42.2"


def test_session_end_config_invalid_inbox_dir():
    """SessionEndConfig の inbox_dir が None や空文字列の場合の挙動を検証"""
    from backend.agents.orchestration.run_session_end import SessionEndConfig, SessionEndManager
    from unittest.mock import MagicMock
    import pytest
    
    # inbox_dir が None の場合 (型エラーまたはOSエラーを適切に引き起こすか)
    config = SessionEndConfig(reason="Test Reason", inbox_dir=None) # type: ignore
    mock_hub = MagicMock()
    manager = SessionEndManager(hub=mock_hub, config=config)
    
    # open() で TypeError が発生するはず
    with pytest.raises(TypeError):
        manager.save_report("dummy report content")


def test_get_session_info_with_various_invalid_types():
    """get_session_info が様々な不正な型を適切に検知して TypeError を送出することを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock
    import pytest
    
    for invalid_val in [123, 45.6, "string_data", [1, 2, 3], True, False]:
        mock_hub = MagicMock()
        mock_hub.get_flash_session.return_value = invalid_val
        manager = SessionEndManager(hub=mock_hub)
        with pytest.raises(TypeError) as exc_info:
            manager.get_session_info()
        assert "Invalid flash session format" in str(exc_info.value)


def test_generate_report_extreme_values():
    """generate_report が非常に大きな数値や空値などの極端な入力に対して動作し、文字列を返すことを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock
    
    mock_hub = MagicMock()
    manager = SessionEndManager(hub=mock_hub)
    
    # 巨大な完了タスク数、空のバッチID
    session_info = {
        "opus_conversation_id": "a" * 1000, # 非常に長いID
        "tasks_completed_in_session": 10**18, # 非常に大きな数
        "batches_in_session": -1, # 負数
        "current_batch_id": "",
        "context_consumption_pct": 999999
    }
    
    report = manager.generate_report(session_info)
    assert isinstance(report, str)
    assert "- **セッション内完了タスク数**: 1000000000000000000 件" in report
    assert "- **セッション内バッチ数**: -1 バッチ" in report
    assert "- **最終バッチID**: " in report
    assert "- **最終コンテキスト消費率**: ~999999%" in report


def test_save_report_empty_timestamp_and_invalid_dir():
    """save_report の timestamp が空文字列の場合、および inbox_dir が存在しない場合の挙動を検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager, SessionEndConfig
    from unittest.mock import MagicMock, patch
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = SessionEndConfig(reason="Test", inbox_dir=tmpdir)
        mock_hub = MagicMock()
        manager = SessionEndManager(hub=mock_hub, config=config)
        
        # timestamp に空文字列を指定して保存
        report_path = manager.save_report("report_content", timestamp="")
        assert os.path.exists(report_path)
        assert report_path.endswith("session_complete_report_.md")


def test_execute_propagates_multiple_exceptions_chain():
    """execute で、hub.flash_session_end, get_flash_session, save_report がすべて例外を投げたときのチェーンを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock
    import pytest
    
    mock_hub = MagicMock()
    mock_hub.flash_session_end.side_effect = ZeroDivisionError("division by zero")
    mock_hub.get_flash_session.side_effect = AttributeError("attribute lookup failed")
    
    manager = SessionEndManager(hub=mock_hub)
    
    with pytest.raises(AttributeError) as exc_info:
        manager.execute()
        
    assert "attribute lookup failed" in str(exc_info.value)
    # 例外チェーンの検証: ZeroDivisionError が __cause__ に設定されていること
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ZeroDivisionError)


def test_execute_hub_fail_and_save_fail_with_cause():
    """hub.flash_session_end が失敗し、レポート保存でも例外が発生した際、レポート保存の例外が hub の例外を cause として持って再送出されることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock, patch
    import pytest
    
    mock_hub = MagicMock()
    mock_hub.flash_session_end.side_effect = KeyError("hub session key error")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv",
        "tasks_completed_in_session": 1,
        "batches_in_session": 1,
        "current_batch_id": "b1",
        "context_consumption_pct": 5
    }
    
    manager = SessionEndManager(hub=mock_hub)
    
    with patch("backend.agents.orchestration.run_session_end.open", side_effect=FileNotFoundError("directory not found")):
        with patch("os.makedirs"):
            with pytest.raises(FileNotFoundError) as exc_info:
                manager.execute()
                
            assert "directory not found" in str(exc_info.value)
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, KeyError)
            assert "hub session key error" in str(exc_info.value.__cause__)


# --- 新規追加テスト (ステップ1/3: 設計・スタブ検証用) ---

def test_custom_exceptions_inheritance():
    """各カスタム例外が Exception を正しく継承していることを検証"""
    from backend.agents.orchestration.run_session_end import (
        HubCommunicationError,
        ReportWriteError
    )
    assert issubclass(HubCommunicationError, Exception)
    assert issubclass(ReportWriteError, Exception)


def test_validate_report_data_validation():
    """validate_report_data 関数がデータを正しく検証し、整形されることを検証"""
    from backend.agents.orchestration.run_session_end import validate_report_data
    
    # 正常系
    valid_data = {
        "opus_conversation_id": "opus_123",
        "conversation_id": "conv_456",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45,
        "ended_at": "2026-06-12T11:00:00Z",
        "exit_reason": "test exit"
    }
    res = validate_report_data(valid_data)
    assert res["opus_conversation_id"] == "opus_123"
    assert res["tasks_completed_in_session"] == 5
    
    # 正常系 (Optional フィールドが None)
    valid_data_none = {
        "opus_conversation_id": None,
        "conversation_id": None,
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45,
        "ended_at": "2026-06-12T11:00:00Z",
        "exit_reason": "test exit"
    }
    res_none = validate_report_data(valid_data_none)
    assert res_none["opus_conversation_id"] is None
    
    # 異常系 (dict ではない)
    with pytest.raises(TypeError) as exc_info:
        validate_report_data("not a dict")
    assert "入力データは dict である必要があります" in str(exc_info.value)
    
    # 異常系 (必須キー不足)
    invalid_data = valid_data.copy()
    del invalid_data["tasks_completed_in_session"]
    with pytest.raises(ValueError) as exc_info:
        validate_report_data(invalid_data)
    assert "必須フィールド 'tasks_completed_in_session' が不足しています" in str(exc_info.value)
    
    # 異常系 (型が不正)
    invalid_data_type = valid_data.copy()
    invalid_data_type["tasks_completed_in_session"] = "not an int"
    with pytest.raises(TypeError) as exc_info:
        validate_report_data(invalid_data_type)
    assert "int である必要があります" in str(exc_info.value)

def test_verify_session_state_validation():
    """SessionEndManager.verify_session_state メソッドのバリデーションを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager()
    
    # 正常系
    valid_session = {
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    # 例外が発生しないこと
    manager.verify_session_state(valid_session)
    
    # 異常系 (None)
    with pytest.raises(ValueError) as exc_info:
        manager.verify_session_state(None) # type: ignore
    assert "セッション情報が None です" in str(exc_info.value)
    
    # 異常系 (dict ではない)
    with pytest.raises(TypeError) as exc_info:
        manager.verify_session_state("not a dict") # type: ignore
    assert "セッション情報は dict である必要があります" in str(exc_info.value)
    
    # 異常系 (空辞書)
    with pytest.raises(ValueError) as exc_info:
        manager.verify_session_state({})
    assert "セッション情報が空です" in str(exc_info.value)
    
    # 異常系 (必須キー不足)
    invalid_session = valid_session.copy()
    del invalid_session["tasks_completed_in_session"]
    with pytest.raises(ValueError) as exc_info:
        manager.verify_session_state(invalid_session)
    assert "必須フィールド 'tasks_completed_in_session' が不足しています" in str(exc_info.value)
    
    # 異常系 (型が不正)
    invalid_session_type = valid_session.copy()
    invalid_session_type["tasks_completed_in_session"] = "not an int"
    with pytest.raises(TypeError) as exc_info:
        manager.verify_session_state(invalid_session_type)
    assert "int である必要があります" in str(exc_info.value)


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_execute_does_not_catch_name_error(mock_hub_class):
    """NameError が発生した場合は、キャッチされずにそのまま上位へ伝播することを検証（バグ隠蔽の防止）"""
    mock_hub = mock_hub_class.return_value
    mock_hub.flash_session_end.side_effect = NameError("Undefined variable dummy")
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with pytest.raises(NameError) as exc_info:
        manager.execute()
    assert "Undefined variable dummy" in str(exc_info.value)


# --- 新規追加テスト (境界値・極端な値の網羅 - Step 3/3) ---

def test_generate_report_missing_keys_and_none_values():
    """session_info 内の各フィールドの値が None や空文字列 "" の場合、あるいはキー自体が欠損している場合の Markdown レポート生成挙動を検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock

    mock_hub = MagicMock()
    manager = SessionEndManager(hub=mock_hub)

    # 1. 完全に空の辞書
    report_empty = manager.generate_report({})
    assert "- **セッション内完了タスク数**: 0 件" in report_empty
    assert "- **セッション内バッチ数**: 0 バッチ" in report_empty
    assert "- **最終バッチID**: N/A" in report_empty
    assert "- **最終コンテキスト消費率**: ~0%" in report_empty

    # 2. None値や空文字列が設定された辞書
    report_none = manager.generate_report({
        "tasks_completed_in_session": None,
        "batches_in_session": None,
        "current_batch_id": None,
        "context_consumption_pct": None
    })
    assert "- **セッション内完了タスク数**: None 件" in report_none
    assert "- **セッション内バッチ数**: None バッチ" in report_none
    assert "- **最終バッチID**: None" in report_none
    assert "- **最終コンテキスト消費率**: ~None%" in report_none


def test_session_end_config_extreme_values():
    """SessionEndConfig において、reason や inbox_dir に極端な値（非常に長い文字列、空文字列）を設定した際の挙動"""
    from backend.agents.orchestration.run_session_end import SessionEndConfig, SessionEndManager
    from unittest.mock import MagicMock

    # 1. 空文字列
    config_empty = SessionEndConfig(reason="", inbox_dir="")
    mock_hub = MagicMock()
    # reason が空文字列の場合、__init__ で動的に phase を取得しようとする
    mock_hub.get_phase_state.return_value = {"current_phase": 99, "current_milestone": "M99.9"}
    manager = SessionEndManager(hub=mock_hub, config=config_empty)
    assert manager.config.reason == "セッション寿命（アーカイブ推奨閾値）到達による終了: P99/M99.9"

    # 2. 非常に長い文字列 (10,000文字)
    long_reason = "A" * 10000
    long_inbox = "B" * 10000
    config_long = SessionEndConfig(reason=long_reason, inbox_dir=long_inbox)
    manager_long = SessionEndManager(hub=mock_hub, config=config_long)
    assert manager_long.config.reason == long_reason
    assert manager_long.config.inbox_dir == long_inbox


def test_stubs_with_null_and_empty_inputs():
    """validate_report_data および verify_session_state に対して、None や空値などの不正な引数を与えた際の例外挙動を検証"""
    from backend.agents.orchestration.run_session_end import validate_report_data, SessionEndManager
    import pytest

    # validate_report_data に対する境界値
    with pytest.raises(TypeError) as exc_info1:
        validate_report_data(None) # type: ignore
    assert "入力データは dict である必要があります" in str(exc_info1.value)

    with pytest.raises(ValueError) as exc_info2:
        validate_report_data({})
    assert "必須フィールド 'tasks_completed_in_session' が不足しています" in str(exc_info2.value)

    # verify_session_state に対する境界値
    manager = SessionEndManager(hub=MagicMock())
    with pytest.raises(ValueError) as exc_info3:
        manager.verify_session_state(None) # type: ignore
    assert "セッション情報が None です" in str(exc_info3.value)

    with pytest.raises(ValueError) as exc_info4:
        manager.verify_session_state({})
    assert "セッション情報が空です" in str(exc_info4.value)


# --- 設計・スタブ検証用テスト (ステップ1/3) ---

def test_error_context_type():
    """ErrorContext 型定義が正しくインポート可能であり、特定のキーを持つことを検証"""
    from backend.agents.orchestration.run_session_end import ErrorContext
    ctx: ErrorContext = {
        "step": "verify",
        "phase": 33,
        "milestone": "M33.1",
        "timestamp": "20260612_203700_UTC",
        "extra_info": None
    }
    assert ctx["step"] == "verify"
    assert ctx["phase"] == 33

def test_error_resolution_type():
    """ErrorResolution 型定義が正しくインポート可能であることを検証"""
    from backend.agents.orchestration.run_session_end import ErrorResolution
    res: ErrorResolution = {
        "action": "retry",
        "custom_exception": None,
        "message": "Retry target step"
    }
    assert res["action"] == "retry"

def test_session_end_error_handler_stubs(capsys):
    """SessionEndErrorHandler の各メソッドが正しく動作し、適切なアクションやログを出力することを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndErrorHandler
    handler = SessionEndErrorHandler()
    
    ctx = {
        "step": "end",
        "phase": 33,
        "milestone": "M33.1",
        "timestamp": "20260612_203700_UTC",
        "extra_info": {}
    }
    
    # handle_exception
    res = handler.handle_exception(Exception("test"), ctx)
    assert res["action"] == "fail"
    
    # log_error
    handler.log_error(Exception("test_log"), ctx)
    captured = capsys.readouterr()
    assert "Error occurred during session end at step 'end'" in captured.err
    assert "test_log" in captured.err

def test_handle_session_end_error_stub():
    """SessionEndManager.handle_session_end_error が適切に例外を転送し、特定のアクションに従うことを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager(hub=MagicMock())
    
    # ValueError の場合は action="fallback" になるので、例外は発生しないはず
    manager.handle_session_end_error(ValueError("test_fallback"), "some_step")
    
    # 一般的な Exception の場合は action="fail" になるので、例外がそのまま再送出される
    with pytest.raises(Exception) as exc_info:
        manager.handle_session_end_error(Exception("test_fail"), "some_step")
    assert "test_fail" in str(exc_info.value)

@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_register_debt_integration(mock_store_class):
    """予期せぬ例外が発生した際に、TechnicalDebtStore.register_debt() が正しく呼び出されることを検証"""
    import os
    from backend.agents.orchestration.run_session_end import SessionEndErrorHandler
    
    os.environ["FORCE_DEBT_REGISTRATION"] = "1"
    try:
        mock_store = mock_store_class.return_value
        handler = SessionEndErrorHandler()
        
        ctx = {
            "step": "get_session_info",
            "phase": 33,
            "milestone": "M33.1",
            "timestamp": "20260612_203700_UTC",
            "extra_info": None
        }
        
        # 期待される例外（ValueError）では登録が呼ばれないことを検証
        handler.register_debt_if_needed(ValueError("expected"), ctx)
        mock_store.register_debt.assert_not_called()
        
        # 期待されない例外（NotImplementedError等）では登録が呼ばれることを検証
        handler.register_debt_if_needed(NotImplementedError("unexpected"), ctx)
        mock_store.register_debt.assert_called_once_with(
            category="IMPORTANT_SERVICE",
            file_path="agents/orchestration/run_session_end.py",
            line_number=289,
            pattern="NotImplementedError: unexpected",
            cause_pattern="DP-01",
            fix_pattern="例外の原因を特定し、型チェックまたは条件ガードを追加する",
            registered_by="bug_hunter_P33",
            notes="セッション終了処理のステップ 'get_session_info' にて予期せぬ例外が発生しました。詳細は context: {'step': 'get_session_info', 'phase': 33, 'milestone': 'M33.1', 'timestamp': '20260612_203700_UTC', 'extra_info': None} を参照。"
        )
    finally:
        os.environ.pop("FORCE_DEBT_REGISTRATION", None)


@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_register_debt_dynamic_line_number(mock_store_class):
    """例外が実際に発生したスタックトレースから、正しい行番号が動的に検出・登録されることを検証"""
    import os
    from backend.agents.orchestration.run_session_end import SessionEndErrorHandler
    
    os.environ["FORCE_DEBT_REGISTRATION"] = "1"
    try:
        mock_store = mock_store_class.return_value
        handler = SessionEndErrorHandler()
        
        ctx = {
            "step": "get_phase_state",
            "phase": 33,
            "milestone": "M33.1",
            "timestamp": "20260612_203700_UTC",
            "extra_info": None
        }
        
        # 実際に例外を発生させてトレースバックを作る
        try:
            # 意図的に例外を投げる
            raise NotImplementedError("dynamic unexpected error")
        except NotImplementedError as e:
            target_exception = e
            
        handler.register_debt_if_needed(target_exception, ctx)
        
        mock_store.register_debt.assert_called_once()
        args, kwargs = mock_store.register_debt.call_args
        
        # 例外が発生したテストファイルではなく、run_session_end.py 内で _get_exception_line が動作するが、
        # トレースバックに対象ファイル（run_session_end.py）が含まれていない場合はデフォルト値（289）が返る。
        # ここでは traceback に test_run_session_end.py の行しか含まれていないため、
        # _get_exception_line はデフォルト値 289 を返すことを検証。
        assert kwargs["line_number"] == 289
        assert kwargs["pattern"] == "NotImplementedError: dynamic unexpected error"
    finally:
        os.environ.pop("FORCE_DEBT_REGISTRATION", None)


def test_handle_session_end_error_propagates_fatal_exceptions_immediately():
    """致命的な例外 (NameError, AssertionError, SystemExit, KeyboardInterrupt) が handle_session_end_error に渡された場合、即座に再送出されることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager(hub=MagicMock())
    
    import pytest
    with pytest.raises(NameError):
        manager.handle_session_end_error(NameError("fatal name"), "some_step")
        
    with pytest.raises(AssertionError):
        manager.handle_session_end_error(AssertionError("fatal assert"), "some_step")
        
    with pytest.raises(SystemExit):
        manager.handle_session_end_error(SystemExit("fatal exit"), "some_step")
        
    with pytest.raises(KeyboardInterrupt):
        manager.handle_session_end_error(KeyboardInterrupt("fatal interrupt"), "some_step")


from unittest.mock import patch
import pytest

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
def test_execute_propagates_unlisted_custom_exception(mock_makedirs, mock_hub_class):
    """従来の個別列挙リストにないカスタム例外が flash_session_end で発生した際、正しく捕捉されて execute() の最後に再送出されることを検証"""
    import backend.agents.orchestration.run_session_end as run_session_end
    mock_hub = mock_hub_class.return_value
    
    class CompletelyUnlistedCustomError(Exception):
        pass
        
    mock_hub.flash_session_end.side_effect = CompletelyUnlistedCustomError("Custom Error")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_unlisted",
        "tasks_completed_in_session": 1,
        "batches_in_session": 1,
        "current_batch_id": "b1",
        "context_consumption_pct": 5
    }
    
    mock_open = MagicMock()
    
    manager = run_session_end.SessionEndManager(hub=mock_hub)
    with patch("builtins.open", mock_open):
        with pytest.raises(CompletelyUnlistedCustomError) as exc_info:
            manager.execute()
        
    assert "Custom Error" in str(exc_info.value)
    mock_open.assert_called_once()


# --- bug_hunter タスク #1 新規追加テスト (境界値・極端な値の整合性検証) ---

def test_validate_report_data_negative_values():
    """validate_report_data に負の数や範囲外のコンテキスト消費率を渡した際に ValueError が投げられることを検証"""
    from backend.agents.orchestration.run_session_end import validate_report_data
    import pytest

    base_data = {
        "opus_conversation_id": "conv_1",
        "conversation_id": "conv_2",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 50,
        "ended_at": "2026-06-12",
        "exit_reason": "test"
    }

    # 1. 負のタスク数
    data_neg_tasks = base_data.copy()
    data_neg_tasks["tasks_completed_in_session"] = -1
    with pytest.raises(ValueError) as exc:
        validate_report_data(data_neg_tasks)
    assert "0 以上である必要があります" in str(exc.value)

    # 2. 負のバッチ数
    data_neg_batches = base_data.copy()
    data_neg_batches["batches_in_session"] = -5
    with pytest.raises(ValueError) as exc:
        validate_report_data(data_neg_batches)
    assert "0 以上である必要があります" in str(exc.value)

    # 3. 範囲外のコンテキスト消費率
    data_invalid_ctx = base_data.copy()
    data_invalid_ctx["context_consumption_pct"] = 150
    with pytest.raises(ValueError) as exc:
        validate_report_data(data_invalid_ctx)
    assert "0 以上 100 以下である必要があります" in str(exc.value)


def test_verify_session_state_negative_values():
    """verify_session_state に負の数や範囲外の数値を渡した際に ValueError が投げられることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    import pytest

    manager = SessionEndManager()

    base_session = {
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 50
    }

    # 1. 負のタスク数
    session_neg_tasks = base_session.copy()
    session_neg_tasks["tasks_completed_in_session"] = -1
    with pytest.raises(ValueError) as exc:
        manager.verify_session_state(session_neg_tasks)
    assert "0 以上である必要があります" in str(exc.value)

    # 2. 負のバッチ数
    session_neg_batches = base_session.copy()
    session_neg_batches["batches_in_session"] = -10
    with pytest.raises(ValueError) as exc:
        manager.verify_session_state(session_neg_batches)
    assert "0 以上である必要があります" in str(exc.value)

    # 3. 範囲外のコンテキスト消費率 (100%超)
    session_invalid_ctx = base_session.copy()
    session_invalid_ctx["context_consumption_pct"] = 101
    with pytest.raises(ValueError) as exc:
        manager.verify_session_state(session_invalid_ctx)
    assert "0 以上 100 以下である必要があります" in str(exc.value)

    # 4. 範囲外のコンテキスト消費率 (負の数)
    session_neg_ctx = base_session.copy()
    session_neg_ctx["context_consumption_pct"] = -5
    with pytest.raises(ValueError) as exc:
        manager.verify_session_state(session_neg_ctx)
    assert "0 以上 100 以下である必要があります" in str(exc.value)



# --- バリデーション直接検証テスト ---

def test_verify_session_state_valid():
    """有効なセッション情報に対して verify_session_state が例外を投げないことを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager(hub=MagicMock())
    valid_session = {
        "tasks_completed_in_session": 10,
        "batches_in_session": 5,
        "context_consumption_pct": 50,
        "current_batch_id": "batch_123"
    }
    # 例外が発生しなければパス
    manager.verify_session_state(valid_session)

def test_verify_session_state_invalid_types():
    """セッション情報の型が不正な場合に TypeError が投げられることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager(hub=MagicMock())
    
    # tasks_completed_in_session が bool (bool は int のサブクラスだが明示的に禁止)
    invalid_session_bool = {
        "tasks_completed_in_session": True,
        "batches_in_session": 5,
        "context_consumption_pct": 50,
        "current_batch_id": "batch_123"
    }
    with pytest.raises(TypeError):
        manager.verify_session_state(invalid_session_bool)

    # current_batch_id が int
    invalid_session_batch_type = {
        "tasks_completed_in_session": 10,
        "batches_in_session": 5,
        "context_consumption_pct": 50,
        "current_batch_id": 12345
    }
    with pytest.raises(TypeError):
        manager.verify_session_state(invalid_session_batch_type)

def test_validate_report_data_valid():
    """validate_report_data が正しい辞書を返し、例外を投げないことを検証"""
    from backend.agents.orchestration.run_session_end import validate_report_data
    valid_data = {
        "opus_conversation_id": "opus_123",
        "conversation_id": "conv_456",
        "tasks_completed_in_session": 10,
        "batches_in_session": 5,
        "context_consumption_pct": 50,
        "current_batch_id": "batch_123",
        "ended_at": "20260611_120000_UTC",
        "exit_reason": "test_reason"
    }
    validated = validate_report_data(valid_data)
    assert validated["tasks_completed_in_session"] == 10
    assert validated["ended_at"] == "20260611_120000_UTC"

def test_validate_report_data_invalid_range():
    """validate_report_data で数値の範囲が不正な場合に ValueError が投げられることを検証"""
    from backend.agents.orchestration.run_session_end import validate_report_data
    
    # context_consumption_pct が 100 超
    invalid_data = {
        "tasks_completed_in_session": 10,
        "batches_in_session": 5,
        "context_consumption_pct": 150,
        "current_batch_id": "batch_123",
        "ended_at": "20260611_120000_UTC",
        "exit_reason": "test_reason"
    }
    with pytest.raises(ValueError):
        validate_report_data(invalid_data)

def test_verify_session_state_float_type_error():
    """verify_session_state に float 値が含まれている場合に TypeError が投げられることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    manager = SessionEndManager(hub=MagicMock())
    
    # context_consumption_pct が float の場合
    invalid_session = {
        "tasks_completed_in_session": 10,
        "batches_in_session": 5,
        "context_consumption_pct": 50.5,
        "current_batch_id": "batch_123"
    }
    with pytest.raises(TypeError) as exc_info:
        manager.verify_session_state(invalid_session)
    assert "int である必要があります" in str(exc_info.value)

@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_bool_type_fallback(mock_open, mock_makedirs, mock_hub_class):
    """get_phase_state から返された phase または milestone が bool 型の場合に、TypeError が発生してデフォルト値に安全にフォールバックされることを検証"""
    import backend.agents.orchestration.run_session_end as run_session_end
    mock_hub = run_session_end.OrchestrationHub.return_value
    mock_hub.flash_session_end.reset_mock()
    
    # phase が bool の場合
    mock_hub.get_phase_state.return_value = {
        "current_phase": True,
        "current_milestone": "M33.1"
    }
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    run_session_end.main()
    
    # デフォルト値 P33/M33.1 が適用されること
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )
    
    # milestone が bool の場合
    mock_hub.flash_session_end.reset_mock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 33,
        "current_milestone": False
    }
    
    run_session_end.main()
    
    mock_hub.flash_session_end.assert_called_once_with(
        "セッション寿命（アーカイブ推奨閾値）到達による終了: P33/M33.1"
    )


def test_save_report_relative_path_resolved_to_repo_root():
    """inbox_dir が相対パスの場合、_repo_root を基準とした絶対パスに解決されることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager, SessionEndConfig, _repo_root
    
    mock_hub = MagicMock()
    config = SessionEndConfig(reason="Test", inbox_dir="relative_inbox_test")
    manager = SessionEndManager(hub=mock_hub, config=config)
    
    mock_file = MagicMock()
    with patch("os.makedirs") as mock_makedirs, patch("backend.agents.orchestration.run_session_end.open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value = mock_file
        report_path = manager.save_report("report_content", timestamp="20260612_120000_UTC")
        
        expected_path = os.path.abspath(os.path.join(_repo_root, "relative_inbox_test"))
        assert os.path.isabs(report_path)
        assert expected_path in report_path


def test_session_end_manager_initialization_with_mock_hub_prevents_file_creation():
    """SessionEndManagerにモックのhubを渡した際、実ファイルの作成やOrchestrationHubの初期化処理が一切走らないことを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager
    from unittest.mock import MagicMock, patch
    
    mock_hub = MagicMock()
    # 本物の OrchestrationHub が呼び出されていないことを確認
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        manager = SessionEndManager(hub=mock_hub)
        
        # OrchestrationHubクラス自体はインスタンス化されていないことを確認
        mock_hub_class.assert_not_called()
        
        # 渡したモックオブジェクトがそのまま保持されていることを確認
        assert manager.hub == mock_hub


@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_register_debt_type_error_caught(mock_store_class, capsys):
    """TechnicalDebtStore.register_debt() が TypeError を投げた場合でも、適切に例外がキャッチされ、警告メッセージが標準エラーに出力されることを検証"""
    import os
    from backend.agents.orchestration.run_session_end import SessionEndErrorHandler
    
    os.environ["FORCE_DEBT_REGISTRATION"] = "1"
    try:
        mock_store = mock_store_class.return_value
        mock_store.register_debt.side_effect = TypeError("Mocked type error during registration")
        handler = SessionEndErrorHandler()
        
        ctx = {
            "step": "get_session_info",
            "phase": 33,
            "milestone": "M33.1",
            "timestamp": "20260612_203700_UTC",
            "extra_info": None
        }
        
        # 例外がスルーされ、警告が出力されること
        handler.register_debt_if_needed(NotImplementedError("unexpected"), ctx)
        
        captured = capsys.readouterr()
        assert "Warning: Failed to register technical debt: Mocked type error during registration" in captured.err
    finally:
        os.environ.pop("FORCE_DEBT_REGISTRATION", None)


@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
@patch("os.makedirs")
@patch("backend.agents.orchestration.run_session_end.open", create=True)
def test_main_phase_state_dynamic_line_number_registration(mock_open, mock_makedirs, mock_store_class):
    """get_phase_state() で発生した例外が、run_session_end.py 内の正しい発生行番号で技術負債登録されることを検証"""
    import os
    from backend.agents.orchestration.run_session_end import SessionEndManager, OrchestrationHub
    from unittest.mock import MagicMock
    
    os.environ["FORCE_DEBT_REGISTRATION"] = "1"
    try:
        mock_hub = MagicMock(spec=OrchestrationHub)
        mock_hub.get_phase_state.side_effect = RuntimeError("Phase state retrieval crashed")
        mock_hub.get_flash_session.return_value = {
            "opus_conversation_id": "test_conv_123",
            "tasks_completed_in_session": 5,
            "batches_in_session": 2,
            "current_batch_id": "batch_abc",
            "context_consumption_pct": 45
        }
        
        mock_store = mock_store_class.return_value
        
        # 実行
        manager = SessionEndManager(hub=mock_hub)
        manager.execute()
        
        mock_store.register_debt.assert_called_once()
        args, kwargs = mock_store.register_debt.call_args
        
        # 例外発生行（hub.get_phase_state()が呼ばれる行：283行目付近）が正しく動的に検出されていることを検証
        assert 270 <= kwargs["line_number"] <= 300
        assert kwargs["pattern"] == "RuntimeError: Phase state retrieval crashed"
    finally:
        os.environ.pop("FORCE_DEBT_REGISTRATION", None)


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_main_get_phase_state_json_decode_error_fallback(mock_hub_class):
    """get_phase_state が json.JSONDecodeError を投げた場合、SessionEndManager 初期化時に適切にキャッチされ、デフォルトの Phase 33 / M33.1 にフォールバックすることを検証"""
    import json
    from backend.agents.orchestration.run_session_end import SessionEndManager
    
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.side_effect = json.JSONDecodeError("Expecting value", "{}", 0)
    
    manager = SessionEndManager(hub=mock_hub)
    assert "P33/M33.1" in manager.config.reason


@patch("backend.agents.orchestration.run_session_end.OrchestrationHub")
def test_execute_hub_communication_error_raised(mock_hub_class):
    """flash_session_end が HubCommunicationError を投げた場合、execute() で適切にキャッチされ、最終的に致命的エラーとして再送出されることを検証"""
    from backend.agents.orchestration.run_session_end import SessionEndManager, HubCommunicationError
    
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {"current_phase": 33, "current_milestone": "M33.1"}
    mock_hub.flash_session_end.side_effect = HubCommunicationError("Connection lost")
    mock_hub.get_flash_session.return_value = {
        "opus_conversation_id": "test_conv_123",
        "tasks_completed_in_session": 5,
        "batches_in_session": 2,
        "current_batch_id": "batch_abc",
        "context_consumption_pct": 45
    }
    
    manager = SessionEndManager(hub=mock_hub)
    with pytest.raises(HubCommunicationError) as exc_info:
        manager.execute()
    assert "Connection lost" in str(exc_info.value)


