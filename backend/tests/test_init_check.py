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

def test_parse_args():
    # 引数がない場合 (デフォルトIDが返ること)
    assert parse_args(["init_check.py"]) == DEFAULT_CONVERSATION_ID
    # 引数がある場合 (引数で渡されたIDが返ること)
    assert parse_args(["init_check.py", "custom-conversation-id"]) == "custom-conversation-id"

def test_run_init_check():
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {"phase": 27}
    mock_hub.get_queue_status.return_value = {"queue": "active"}
    mock_hub.generate_flash_status.return_value = {"status": "running"}

    captured_output = io.StringIO()
    with patch('sys.stdout', new=captured_output):
        run_init_check("test-conv-id", hub=mock_hub)
        
        mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id")
        mock_hub.get_phase_state.assert_called_once()
        mock_hub.get_queue_status.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()

        output_text = captured_output.getvalue()
        assert "PHASE_STATE:{\"phase\": 27}\n" in output_text
        assert "QUEUE_STATUS:{\"queue\": \"active\"}\n" in output_text
        assert "FLASH_STATUS:{\"status\": \"running\"}\n" in output_text

def test_main():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {"phase": 27}
    mock_hub_instance.get_queue_status.return_value = {"queue": "empty"}
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance), \
         patch('sys.argv', ["init_check.py", "arg-conv-id"]), \
         patch('sys.stdout', new_callable=io.StringIO):
        main()
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("arg-conv-id")

def test_main_error_handling():
    with patch('backend.agents.orchestration.init_check.parse_args', side_effect=ValueError("Mocked error")), \
         patch('sys.stderr', new_callable=io.StringIO) as mock_stderr, \
         pytest.raises(SystemExit) as exc_info:
        main()
    
    assert exc_info.value.code == 1
    assert "Error during init check: Mocked error" in mock_stderr.getvalue()

def test_sys_path_insertion():
    import importlib
    import backend.agents.orchestration.init_check as init_check
    project_root = init_check.project_root
    
    original_path = sys.path.copy()
    try:
        # sys.path から project_root を除去する
        sys.path = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(project_root)]
        
        # リロードして sys.path.insert(0, project_root) を実行させる
        importlib.reload(init_check)
        
        assert sys.path[0] == project_root
    finally:
        sys.path = original_path

