import sys
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

def test_run_init_check_default_hub():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {"phase": 27}
    mock_hub_instance.get_queue_status.return_value = {"queue": "active"}
    mock_hub_instance.generate_flash_status.return_value = {"status": "running"}

    with patch('backend.agents.orchestration.init_check.OrchestrationHub', return_value=mock_hub_instance), \
         patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
        run_init_check("test-conv-id", hub=None)
        
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("test-conv-id")
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_queue_status.assert_called_once()
        mock_hub_instance.generate_flash_status.assert_called_once()

        output_text = mock_stdout.getvalue()
        assert "PHASE_STATE:{\"phase\": 27}\n" in output_text
        assert "QUEUE_STATUS:{\"queue\": \"active\"}\n" in output_text
        assert "FLASH_STATUS:{\"status\": \"running\"}\n" in output_text

def test_parse_args_edge_cases():
    # 引数が空リストの場合
    assert parse_args([]) == DEFAULT_CONVERSATION_ID
    # 引数が3つ以上ある場合
    assert parse_args(["init_check.py", "custom-id", "extra-arg"]) == "custom-id"

def test_sys_path_insertion_coverage():
    import importlib
    import backend.agents.orchestration.init_check as init_check
    
    target_project_root = init_check.project_root
    
    original_path = sys.path.copy()
    try:
        while target_project_root in sys.path:
            sys.path.remove(target_project_root)
        
        importlib.reload(init_check)
        
        assert sys.path[0] == target_project_root
    finally:
        sys.path = original_path

def test_sys_path_already_contains_project_root_no_insert():
    import importlib
    import backend.agents.orchestration.init_check as init_check
    
    target_project_root = init_check.project_root
    
    original_path = sys.path.copy()
    try:
        # sys.path の先頭以外に project_root を追加しておく
        while target_project_root in sys.path:
            sys.path.remove(target_project_root)
        sys.path.append(target_project_root)
        
        importlib.reload(init_check)
        
        # すでに含まれているので、先頭 (sys.path[0]) には挿入されないはず
        assert sys.path[0] != target_project_root
        assert target_project_root in sys.path
    finally:
        sys.path = original_path

def test_run_init_check_non_standard_return_types():
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = "non-dict-phase"
    mock_hub.get_queue_status.return_value = 42
    mock_hub.generate_flash_status.return_value = None

    with patch('sys.stdout', new_callable=io.StringIO) as mock_stdout:
        run_init_check("test-conv-id", hub=mock_hub)
        
        output_text = mock_stdout.getvalue()
        assert 'PHASE_STATE:"non-dict-phase"\n' in output_text
        assert 'QUEUE_STATUS:42\n' in output_text
        assert 'FLASH_STATUS:null\n' in output_text

