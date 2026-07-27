# -*- coding: utf-8 -*-
# Test flash_assign_subagents_5

import sys
import json
from unittest.mock import MagicMock, patch
import pytest

import backend.agents.orchestration.flash_assign_subagents_5 as flash_assign

def test_main_success_change():
    test_queue = {
        "tasks": [
            {"id": "T-batch_c4f4d2-thumbnail-000", "assigned_agent": None},
            {"id": "T-batch_c4f4d2-thumbnail-001", "assigned_agent": "old-agent"},
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        result = flash_assign.main()
        assert result == 0
        mock_read.assert_called_once()
        mock_write.assert_called_once()
        
        written_queue = mock_write.call_args[0][1]
        assert written_queue["tasks"][0]["assigned_agent"] == "ee2c86d7-b0d5-45ef-9dcc-0850709d9290"
        assert written_queue["tasks"][1]["assigned_agent"] == "012b1c49-1ed6-4203-9d98-b0abcafa09df"
        assert written_queue["tasks"][2]["assigned_agent"] is None
        assert any(args[0] == "Updated task queue with assigned agents." for args, kwargs in mock_print.call_args_list)

def test_main_no_change():
    test_queue = {
        "tasks": [
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        result = flash_assign.main()
        assert result == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        assert any(args[0] == "No tasks updated." for args, kwargs in mock_print.call_args_list)

def test_main_missing_tasks_key():
    test_queue = {}
    
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        result = flash_assign.main()
        assert result == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        assert any(args[0] == "No tasks updated." for args, kwargs in mock_print.call_args_list)

@pytest.mark.parametrize("side_effect, expected_msg", [
    (FileNotFoundError("File not found"), "Error: Task queue file not found"),
    (json.JSONDecodeError("Expecting value", "", 0), "Error: Failed to parse task queue JSON"),
    (UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte"), "Error: Encoding error occurred when reading task queue file"),
    (PermissionError("Permission denied"), "Error: Permission denied when reading task queue file"),
    (OSError("OS error"), "Error: OS error occurred when reading task queue file")
])
def test_main_read_errors(side_effect, expected_msg):
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", side_effect=side_effect), \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)

@pytest.mark.parametrize("queue_data, expected_msg", [
    (["not", "a", "dict"], "Error: Task queue content is not a valid JSON object."),
    ({"tasks": "not a list"}, "Error: 'tasks' key in task queue is not a list."),
    ({"tasks": ["not a dict"]}, "Error: Task at index 0 is not a valid JSON object."),
    ({"tasks": [{"assigned_agent": None}]}, "Error: Task at index 0 is missing 'id' key.")
])
def test_main_validation_errors(queue_data, expected_msg):
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=queue_data), \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)

@pytest.mark.parametrize("side_effect, expected_msg", [
    (PermissionError("Permission denied"), "Error: Permission denied when writing task queue file"),
    (OSError("OS error"), "Error: OS error occurred when writing task queue file")
])
def test_main_write_errors(side_effect, expected_msg):
    test_queue = {
        "tasks": [
            {"id": "T-batch_c4f4d2-thumbnail-000", "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json", side_effect=side_effect) as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_called_once()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_unexpected_exception():
    class BadQueue(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("Unexpected validation error")

    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=BadQueue()) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Unexpected error occurred: Unexpected validation error" in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_validation_error_type():
    class BadQueue(dict):
        def get(self, *args, **kwargs):
            raise TypeError("Mock TypeError")

    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=BadQueue()) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Invalid data format or validation failed: Mock TypeError" in args[0] for args, kwargs in mock_print.call_args_list)

def test_read_json_file_not_found(tmp_path):
    non_existent = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        flash_assign._read_json(non_existent)

def test_read_json_invalid_json(tmp_path):
    invalid_file = tmp_path / "invalid.json"
    with open(invalid_file, "w", encoding="utf-8") as f:
        f.write("{invalid_json}")
    with pytest.raises(json.JSONDecodeError):
        flash_assign._read_json(invalid_file)

def test_main_unexpected_exception_prints_traceback():
    class BadQueue(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("Traceback test exception")

    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=BadQueue()), \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print, \
         patch("traceback.print_exc") as mock_traceback:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        mock_traceback.assert_called_once()

def test_main_invalid_task_id_type():
    test_queue = {
        "tasks": [
            {"id": ["unhashable", "list"], "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Invalid task ID type at index 0:" in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_task_missing_assigned_agent():
    test_queue = {
        "tasks": [
            {"id": "other-task"}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents_5._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_5._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        assert any("No tasks updated." in args[0] for args, kwargs in mock_print.call_args_list)

