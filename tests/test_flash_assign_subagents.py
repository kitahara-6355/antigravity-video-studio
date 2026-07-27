# -*- coding: utf-8 -*-
# Test flash_assign_subagents

import sys
import json
import runpy
from unittest.mock import MagicMock, patch
import pytest

import backend.agents.orchestration.flash_assign_subagents as flash_assign

def test_main_success_change():
    mappings = flash_assign.mappings
    test_key1 = list(mappings.keys())[0] if mappings else "dummy-key-1"
    test_val1 = list(mappings.values())[0] if mappings else "dummy-val-1"
    test_key2 = list(mappings.keys())[1] if len(mappings) > 1 else "dummy-key-2"
    test_val2 = list(mappings.values())[1] if len(mappings) > 1 else "dummy-val-2"
    
    test_queue = {
        "tasks": [
            {"id": test_key1, "assigned_agent": None},
            {"id": test_key2, "assigned_agent": "old-agent"},
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 0
        mock_read.assert_called_once()
        mock_write.assert_called_once()
        
        written_queue = mock_write.call_args[0][1]
        assert written_queue["tasks"][0]["assigned_agent"] == test_val1
        assert written_queue["tasks"][1]["assigned_agent"] == test_val2
        assert written_queue["tasks"][2]["assigned_agent"] is None
        mock_print.assert_any_call("Updated task queue with assigned agents.")

def test_main_no_change():
    test_queue = {
        "tasks": [
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        mock_print.assert_any_call("No tasks updated.")

def test_main_missing_tasks_key():
    test_queue = {}
    
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        mock_print.assert_any_call("No tasks updated.")

def test_main_file_not_found():
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", side_effect=FileNotFoundError("File not found")), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Task queue file not found" in args[0] for args, kwargs in mock_print.call_args_list)

@pytest.mark.parametrize("side_effect, expected_msg", [
    (json.JSONDecodeError("Expecting value", "", 0), "Error: Failed to parse task queue JSON"),
    (UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte"), "Error: Encoding error occurred when reading task queue file"),
    (PermissionError("Permission denied"), "Error: Permission denied when reading task queue file"),
    (OSError("OS error"), "Error: OS error occurred when reading task queue file")
])
def test_main_read_errors(side_effect, expected_msg):
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", side_effect=side_effect), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
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
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=queue_data), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)

@pytest.mark.parametrize("side_effect, expected_msg", [
    (PermissionError("Permission denied"), "Error: Permission denied when writing task queue file"),
    (OSError("OS error"), "Error: OS error occurred when writing task queue file")
])
def test_main_write_errors(side_effect, expected_msg):
    mappings = flash_assign.mappings
    test_key1 = list(mappings.keys())[0] if mappings else "dummy-key-1"
    test_queue = {
        "tasks": [
            {"id": test_key1, "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json", side_effect=side_effect) as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_called_once()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)



def test_main_invalid_task_id_type():
    test_queue = {
        "tasks": [
            {"id": ["unhashable", "list"], "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Invalid task ID type" in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_task_missing_assigned_agent():
    test_queue = {
        "tasks": [
            {"id": "other-task"}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 0
        mock_read.assert_called_once()
        mock_write.assert_not_called()
        assert any("No tasks updated." in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_block_execution():
    sys.modules.pop("backend.agents.orchestration.flash_assign_subagents", None)
    test_queue = {"tasks": []}
    
    with patch("backend.agents.orchestration.orchestrator._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.orchestrator._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
         
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("backend.agents.orchestration.flash_assign_subagents", run_name="__main__")
        assert exc_info.value.code == 0
        
        mock_write.assert_not_called()
        mock_print.assert_any_call("No tasks updated.")

def test_main_invalid_task_id_type_non_str():
    # Make sure we load the latest module after block execution pop
    import backend.agents.orchestration.flash_assign_subagents as local_flash_assign
    test_queue = {
        "tasks": [
            {"id": 12345, "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents._write_json") as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert local_flash_assign.main() == 1
        mock_write.assert_not_called()
        assert any("Error: Invalid task ID type at index 0. Expected string" in args[0] for args, kwargs in mock_print.call_args_list)


