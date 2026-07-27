#- -*- coding: utf-8 -*-
# Test flash_assign_subagents_12

import sys
import json
from unittest.mock import MagicMock, patch
import pytest

import backend.agents.orchestration.flash_assign_subagents_12 as flash_assign

def test_assign_subagents_success():
    test_queue = {
        "tasks": [
            {"id": "T-batch_131274-thumbnail-000", "assigned_agent": None},
            {"id": "T-batch_131274-thumbnail-001", "assigned_agent": "old-agent"},
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write:
        
        mappings = {
            "T-batch_131274-thumbnail-000": "new-agent-000",
            "T-batch_131274-thumbnail-001": "new-agent-001"
        }
        
        result = flash_assign.assign_subagents(mappings)
        assert result is True
        mock_read.assert_called_once()
        mock_write.assert_called_once()
        
        written_queue = mock_write.call_args[0][1]
        assert written_queue["tasks"][0]["assigned_agent"] == "new-agent-000"
        assert written_queue["tasks"][1]["assigned_agent"] == "new-agent-001"
        assert written_queue["tasks"][2]["assigned_agent"] is None

def test_assign_subagents_no_change():
    test_queue = {
        "tasks": [
            {"id": "other-task", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=test_queue) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write:
        
        mappings = {
            "T-batch_131274-thumbnail-000": "new-agent-000"
        }
        
        result = flash_assign.assign_subagents(mappings)
        assert result is False
        mock_read.assert_called_once()
        mock_write.assert_not_called()

def test_update_heartbeat():
    mock_hub = MagicMock()
    flash_assign.update_heartbeat(mock_hub, "test-conv-id")
    mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id")
    mock_hub.flash_update_heartbeat.assert_called_once()

def test_display_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "mock formatted status"}
    
    with patch("builtins.print") as mock_print:
        flash_assign.display_status(mock_hub)
        mock_hub.generate_flash_status.assert_called_once()
        mock_print.assert_any_call("mock formatted status")

def test_main_runs_successfully():
    mock_queue = {
        "tasks": [
            {"id": "T-batch_131274-thumbnail-000", "assigned_agent": None}
        ]
    }
    
    with patch("backend.agents.orchestration.flash_assign_subagents_12.OrchestrationHub") as mock_hub_cls, \
         patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=mock_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write, \
         patch("builtins.print"):
        
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "status"}
        mock_hub_cls.return_value = mock_hub
        
        res = flash_assign.main()
        assert res == 0

@pytest.mark.parametrize("side_effect, expected_msg", [
    (FileNotFoundError("File not found"), "Error: Task queue file not found"),
    (json.JSONDecodeError("Expecting value", "", 0), "Error: Failed to parse task queue JSON"),
    (UnicodeDecodeError("utf-8", b'', 0, 1, "invalid byte"), "Error: Encoding error occurred when reading task queue file"),
    (PermissionError("Permission denied"), "Error: Permission denied when reading task queue file"),
    (OSError("OS error"), "Error: OS error occurred when reading task queue file")
])
def test_main_read_errors(side_effect, expected_msg):
    with patch("backend.agents.orchestration.flash_assign_subagents_12.OrchestrationHub"), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", side_effect=side_effect), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write, \
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
    with patch("backend.agents.orchestration.flash_assign_subagents_12.OrchestrationHub"), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=queue_data), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write, \
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
            {"id": "T-batch_131274-thumbnail-000", "assigned_agent": None}
        ]
    }
    with patch("backend.agents.orchestration.flash_assign_subagents_12.OrchestrationHub"), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=test_queue), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json", side_effect=side_effect) as mock_write, \
         patch("builtins.print") as mock_print:
        
        assert flash_assign.main() == 1
        mock_write.assert_called_once()
        assert any(expected_msg in args[0] for args, kwargs in mock_print.call_args_list)

def test_main_unexpected_exception():
    class BadQueue(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("Unexpected validation error")

    with patch("backend.agents.orchestration.flash_assign_subagents_12.OrchestrationHub"), \
         patch("backend.agents.orchestration.flash_assign_subagents_12._read_json", return_value=BadQueue()) as mock_read, \
         patch("backend.agents.orchestration.flash_assign_subagents_12._write_json") as mock_write, \
         patch("builtins.print") as mock_print, \
         patch("traceback.print_exc") as mock_traceback:
        
        assert flash_assign.main() == 1
        mock_write.assert_not_called()
        mock_traceback.assert_called_once()
        assert any("Error: Unexpected error occurred: Unexpected validation error" in args[0] for args, kwargs in mock_print.call_args_list)
