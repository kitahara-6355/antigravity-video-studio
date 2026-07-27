import os
import sys
import importlib
from unittest.mock import MagicMock, patch
import json
import pytest

def test_get_status_execution():
    original_path = list(sys.path)
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {"phase": 27}
    mock_hub_instance.generate_flash_status.return_value = "running"
    mock_hub_instance.get_queue_status.return_value = {"pending": 0}
    
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance), \
            patch('builtins.print') as mock_print:
             
            if 'backend.scratch.get_status' in sys.modules:
                importlib.reload(sys.modules['backend.scratch.get_status'])
            else:
                importlib.import_module('backend.scratch.get_status')
            
            mock_hub_instance.get_phase_state.assert_called_once()
            mock_hub_instance.generate_flash_status.assert_called_once()
            mock_hub_instance.get_queue_status.assert_called_once()
            
            mock_print.assert_called_once()
            printed_arg = mock_print.call_args[0][0]
            printed_data = json.loads(printed_arg)
            
            assert printed_data["status"] == "running"
            assert printed_data["queue_status"] == {"pending": 0}
            assert printed_data["state"] == {"phase": 27}
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']

def test_get_status_exception_handling():
    original_path = list(sys.path)
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Database connection failed")
    
    mock_stderr = MagicMock()
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance), \
            patch('sys.stderr', mock_stderr), \
            patch('builtins.print') as mock_print:
             
            with pytest.raises(SystemExit) as exc_info:
                if 'backend.scratch.get_status' in sys.modules:
                    importlib.reload(sys.modules['backend.scratch.get_status'])
                else:
                    importlib.import_module('backend.scratch.get_status')
            
            assert exc_info.value.code == 1
            mock_hub_instance.get_phase_state.assert_called_once()
            mock_print.assert_not_called()
            
            # verify stderr was written to
            assert mock_stderr.write.called
            written_args = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
            err_data = json.loads(written_args)
            assert "Database connection failed" in err_data["error"]
            assert "traceback" in err_data
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']


def test_get_status_sys_path_insertion():
    original_path = list(sys.path)
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = ""
    mock_hub_instance.get_queue_status.return_value = {}
    
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance), \
            patch('builtins.print'):
             
            if 'backend.scratch.get_status' in sys.modules:
                importlib.reload(sys.modules['backend.scratch.get_status'])
            else:
                importlib.import_module('backend.scratch.get_status')
            
            assert sys.path[0] == "C:/Users/PC_User/Desktop/script/video-automation"
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']

def test_get_status_hub_initialization_failure():
    original_path = list(sys.path)
    
    mock_stderr = MagicMock()
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', side_effect=ValueError("Init failed")), \
             patch('sys.stderr', mock_stderr), \
             patch('builtins.print') as mock_print:
             
            with pytest.raises(SystemExit) as exc_info:
                if 'backend.scratch.get_status' in sys.modules:
                    importlib.reload(sys.modules['backend.scratch.get_status'])
                else:
                    importlib.import_module('backend.scratch.get_status')
            
            assert exc_info.value.code == 1
            mock_print.assert_not_called()
            
            written_args = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
            err_data = json.loads(written_args)
            assert "Init failed" in err_data["error"]
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']


def test_get_status_print_broken_pipe():
    original_path = list(sys.path)
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {"phase": 27}
    mock_hub_instance.generate_flash_status.return_value = "running"
    mock_hub_instance.get_queue_status.return_value = {"pending": 0}
    
    mock_stderr = MagicMock()
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance), \
             patch('sys.stderr', mock_stderr), \
             patch('builtins.print', side_effect=OSError(22, "Invalid argument")) as mock_print:
             
            with pytest.raises(SystemExit) as exc_info:
                if 'backend.scratch.get_status' in sys.modules:
                    importlib.reload(sys.modules['backend.scratch.get_status'])
                else:
                    importlib.import_module('backend.scratch.get_status')
            
            assert exc_info.value.code == 1
            mock_hub_instance.get_phase_state.assert_called_once()
            mock_print.assert_called_once()
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']


def test_get_status_exception_details():
    original_path = list(sys.path)
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {"phase": 27}
    mock_hub_instance.generate_flash_status.side_effect = ValueError("Invalid status generated")
    
    mock_stderr = MagicMock()
    try:
        with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub_instance), \
             patch('sys.stderr', mock_stderr), \
             patch('builtins.print') as mock_print:
             
            with pytest.raises(SystemExit) as exc_info:
                if 'backend.scratch.get_status' in sys.modules:
                    importlib.reload(sys.modules['backend.scratch.get_status'])
                else:
                    importlib.import_module('backend.scratch.get_status')
            
            assert exc_info.value.code == 1
            mock_print.assert_not_called()
            
            # verify detailed JSON err structure
            written_args = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
            err_data = json.loads(written_args)
            assert err_data["error"] == "Invalid status generated"
            assert "ValueError" in err_data["traceback"]
            
    finally: 
        sys.path = original_path
        if 'backend.scratch.get_status' in sys.modules:
            del sys.modules['backend.scratch.get_status']

