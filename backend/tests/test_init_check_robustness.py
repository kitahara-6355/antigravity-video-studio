import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import json
import io
from unittest.mock import MagicMock, patch
import pytest

from backend.agents.orchestration.init_check import (
    parse_args,
    run_init_check,
    main,
    DEFAULT_CONVERSATION_ID
)

def test_parse_args_empty_string():
    # 引数が空文字列の場合も正しく動作することを確認
    assert parse_args(["init_check.py", ""]) == ""

def test_parse_args_none_and_multiple():
    # None要素や様々な型が混入した場合の挙動を検証 (安全性の確認)
    assert parse_args(["init_check.py", None]) is None
    assert parse_args(["init_check.py", "first", "second", "third"]) == "first"

def test_run_init_check_hub_raises_exception():
    # OrchestrationHub が例外を送出した場合に、例外が正しく伝搬されることを確認
    mock_hub = MagicMock()
    mock_hub.get_phase_state.side_effect = RuntimeError("Hub processing failed")

    with pytest.raises(RuntimeError) as exc_info:
        run_init_check("test-conv-id", hub=mock_hub)
    
    assert str(exc_info.value) == "Hub processing failed"
    mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id")
    mock_hub.get_phase_state.assert_called_once()
    # 例外が発生したため、get_queue_status や generate_flash_status は呼ばれないこと
    mock_hub.get_queue_status.assert_not_called()
    mock_hub.generate_flash_status.assert_not_called()

def test_run_init_check_none_conversation_id():
    # conversation_id が None の場合でも register_flash_conversation_id が呼ばれることを確認
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {}
    mock_hub.get_queue_status.return_value = {}
    mock_hub.generate_flash_status.return_value = {}

    with patch('sys.stdout', new_callable=io.StringIO):
        run_init_check(None, hub=mock_hub)
        mock_hub.register_flash_conversation_id.assert_called_once_with(None)

def test_main_empty_sys_argv():
    # sys.argv が空の状態で main() が呼ばれた場合のテスト
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {}
    mock_hub_instance.get_queue_status.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = {}

    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance),          patch('sys.argv', []),          patch('sys.stdout', new_callable=io.StringIO):
        main()
        # 引数がないため DEFAULT_CONVERSATION_ID で登録されること
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with(DEFAULT_CONVERSATION_ID)

def test_run_init_check_outputs_formatting():
    # run_init_check が出力する PHASE_STATE:, QUEUE_STATUS:, FLASH_STATUS: の直後が有効なJSONであることを検証
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {"phase": 27, "nested": {"key": "value"}}
    mock_hub.get_queue_status.return_value = {"running": 5}
    mock_hub.generate_flash_status.return_value = ["item1", "item2"]

    captured_output = io.StringIO()
    with patch('sys.stdout', new=captured_output):
        run_init_check("test-format-id", hub=mock_hub)
        
        output_lines = captured_output.getvalue().splitlines()
        
        # 各行が期待される接頭辞で始まり、かつJSONデコード可能であることを確認
        prefixes = ["PHASE_STATE:", "QUEUE_STATUS:", "FLASH_STATUS:"]
        assert len(output_lines) >= 3
        for line, prefix in zip(output_lines[:3], prefixes):
            assert line.startswith(prefix)
            json_str = line[len(prefix):]
            decoded = json.loads(json_str)
            assert decoded is not None

def test_parse_args_extremely_long():
    # 非常に長い引数が渡された場合でも正常に最初の引数が会話IDとしてパースされることを検証
    long_id = "a" * 10000
    assert parse_args(["init_check.py", long_id]) == long_id

def test_main_raises_exception_handled():
    # OrchestrationHub が例外を送出したときに、main() 内の try-except が機能し、
    # sys.stderr に書き込み、かつ sys.exit(1) で終了することを検証する。
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Hub crash")

    captured_stderr = io.StringIO()
    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance), \
         patch('sys.argv', ["init_check.py"]), \
         patch('sys.stderr', new=captured_stderr):
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        # sys.exit(1) で終了していることを検証
        assert exc_info.value.code == 1
        # エラーメッセージが標準エラー出力に出力されていることを検証
        assert "Error during init check: Hub crash" in captured_stderr.getvalue()

def test_main_argv_is_none():
    # sys.argv が None の場合に main() が TypeError をキャッチし、
    # sys.stderr に書き込み、sys.exit(1) で終了することを検証する。
    captured_stderr = io.StringIO()
    with patch('sys.argv', None), \
         patch('sys.stderr', new=captured_stderr):
        
        with pytest.raises(SystemExit) as exc_info:
            main()
            
        assert exc_info.value.code == 1
        assert "Error during init check:" in captured_stderr.getvalue()
        assert "object of type 'NoneType' has no len" in captured_stderr.getvalue()

def test_run_init_check_default_hub_fails():
    # hub=None で run_init_check が呼ばれた際、デフォルトで生成される OrchestrationHub 
    # が例外を投げた場合にその例外が正しく呼び出し元に伝播されることを検証する。
    with patch('backend.agents.orchestration.init_check.OrchestrationHub', side_effect=RuntimeError("Hub initialization failed")):
        with pytest.raises(RuntimeError) as exc_info:
            run_init_check("test-conv-id", hub=None)
        assert str(exc_info.value) == "Hub initialization failed"

def test_main_json_serialization_error():
    # OrchestrationHub からの返却値が JSON シリアライズ不可（例: object()）である場合、
    # json.dumps で TypeError が発生し、それが main() 内で適切にキャッチされ、
    # 標準エラー出力にエラーが書き込まれて sys.exit(1) となることを検証する。
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = object()  # json.dumps() で例外が発生する
    mock_hub_instance.get_queue_status.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = {}

    captured_stderr = io.StringIO()
    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance), \
         patch('sys.argv', ["init_check.py", "test-conv-id"]), \
         patch('sys.stderr', new=captured_stderr):
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 1
        assert "Error during init check: Object of type object is not JSON serializable" in captured_stderr.getvalue()

def test_parse_args_multiple_extra_args():
    # 引数が大量（100個など）に渡された場合でも、parse_args が破綻せず最初の会話IDを取得し、
    # main() が正常に実行されることを検証する。
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {}
    mock_hub_instance.get_queue_status.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = {}

    extra_args = ["extra-arg"] * 100
    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance), \
         patch('sys.argv', ["init_check.py", "custom-conv-id"] + extra_args), \
         patch('sys.stdout', new_callable=io.StringIO):
        
        main()
        
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("custom-conv-id")




