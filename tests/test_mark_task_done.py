import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_task_done

def test_main_insufficient_arguments(capsys):
    # 引数が不足している場合 (len(sys.argv) < 3)
    test_args = ["mark_task_done.py", "task-123"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as excinfo:
            mark_task_done.main()
        assert excinfo.value.code == 1
    
    captured = capsys.readouterr()
    assert "Usage: python mark_task_done.py <task_id> <result> '<report_json>'" in captured.out

def test_main_success_with_argument_json(capsys):
    # 引数としてJSON文字列が渡される場合
    test_args = ["mark_task_done.py", "task-123", "success", '{"key": "value"}']
    
    mock_hub_instance = MagicMock()
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_done.OrchestrationHub", return_value=mock_hub_instance):
            mark_task_done.main()
            
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "success", {"key": "value"})
    
    captured = capsys.readouterr()
    assert "Successfully marked task task-123 as success" in captured.out

def test_main_success_with_stdin_json(capsys):
    # 3番目の引数が '-' で、stdinからJSONを読み込む場合
    test_args = ["mark_task_done.py", "task-123", "success", "-"]
    mock_hub_instance = MagicMock()
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_done.OrchestrationHub", return_value=mock_hub_instance):
            with patch("sys.stdin.read", return_value='{"stdin_key": "stdin_value"}'):
                mark_task_done.main()
                
    mock_hub_instance.mark_task_done.assert_called_once_with("task-123", "success", {"stdin_key": "stdin_value"})
    
    captured = capsys.readouterr()
    assert "Successfully marked task task-123 as success" in captured.out

def test_main_invalid_argument_json(capsys):
    # 引数のJSONが不正な場合
    test_args = ["mark_task_done.py", "task-123", "success", "invalid-json"]
    mock_hub_instance = MagicMock()
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_done.OrchestrationHub", return_value=mock_hub_instance):
            with pytest.raises(SystemExit) as excinfo:
                mark_task_done.main()
            assert excinfo.value.code == 1
            
    captured = capsys.readouterr()
    assert "Failed to parse JSON argument:" in captured.out

def test_main_invalid_stdin_json(capsys):
    # stdinのJSONが不正な場合
    test_args = ["mark_task_done.py", "task-123", "success", "-"]
    mock_hub_instance = MagicMock()
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_task_done.OrchestrationHub", return_value=mock_hub_instance):
            with patch("sys.stdin.read", return_value="invalid-json-from-stdin"):
                with pytest.raises(SystemExit) as excinfo:
                    mark_task_done.main()
                assert excinfo.value.code == 1
                
    captured = capsys.readouterr()
    assert "Failed to parse JSON from stdin:" in captured.out
