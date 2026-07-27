import sys
import json
import logging
from unittest.mock import MagicMock, patch
import pytest
import runpy

from backend.agents.orchestration.flash_runner_next_batch_5 import (
    initialize_orchestration_hub,
    update_flash_heartbeat,
    fetch_next_task_batch,
    fetch_flash_status,
    main,
    DEFAULT_FLASH_CONVERSATION_ID,
    _is_configuration_or_known_runtime_error,
)

def test_initialize_orchestration_hub():
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub") as mock_hub_class:
        mock_hub_instance = MagicMock()
        mock_hub_class.return_value = mock_hub_instance
        
        hub = initialize_orchestration_hub()
        mock_hub_class.assert_called_once()
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with(DEFAULT_FLASH_CONVERSATION_ID)
        assert hub == mock_hub_instance

        mock_hub_class.reset_mock()
        mock_hub_instance.reset_mock()
        custom_id = "test-conv-id"
        hub = initialize_orchestration_hub(custom_id)
        mock_hub_class.assert_called_once()
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with(custom_id)

def test_update_flash_heartbeat():
    mock_hub = MagicMock()
    update_flash_heartbeat(mock_hub)
    mock_hub.flash_update_heartbeat.assert_called_once()

def test_fetch_next_task_batch():
    mock_hub = MagicMock()
    expected_batch = {"tasks": [{"id": 1, "name": "Task 1"}]}
    mock_hub.get_next_batch.return_value = expected_batch
    
    result = fetch_next_task_batch(mock_hub, phase=27, milestone="M27.1", batch_size=8)
    
    mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=8)
    assert result == expected_batch

def test_fetch_flash_status():
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "Status: OK"}
    
    result = fetch_flash_status(mock_hub)
    
    mock_hub.generate_flash_status.assert_called_once()
    assert result == {"formatted": "Status: OK"}

def test_main_success():
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {}
    mock_hub.generate_flash_status.return_value = {"formatted": "OK"}
    
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.OrchestrationHub", return_value=mock_hub):
        main()
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.get_next_batch.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()

def test_main_runtime_exception():
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.initialize_orchestration_hub") as mock_init:
        mock_init.side_effect = ValueError("Simulated Config/Runtime Error")
        
        with patch("backend.agents.orchestration.flash_runner_next_batch_5.logger") as mock_logger:
            with pytest.raises(SystemExit) as excinfo:
                main()
            
            assert excinfo.value.code == 1
            mock_logger.error.assert_called_once_with("Error in flash_runner_next_batch_5: Configuration or runtime error: Simulated Config/Runtime Error")

def test_main_unexpected_exception():
    with patch("backend.agents.orchestration.flash_runner_next_batch_5.initialize_orchestration_hub") as mock_init:
        mock_init.side_effect = Exception("Simulated Unexpected Error")
        
        with patch("backend.agents.orchestration.flash_runner_next_batch_5.logger") as mock_logger:
            with pytest.raises(SystemExit) as excinfo:
                main()
            
            assert excinfo.value.code == 1
            mock_logger.error.assert_called_once_with("Error in flash_runner_next_batch_5: Unexpected error: Simulated Unexpected Error")

def test_run_as_main():
    mock_hub = MagicMock()
    mock_hub.get_next_batch.return_value = {}
    mock_hub.generate_flash_status.return_value = {"formatted": "OK"}
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        runpy.run_module("backend.agents.orchestration.flash_runner_next_batch_5", run_name="__main__")
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.get_next_batch.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()

def test_is_configuration_or_known_runtime_error():
    assert _is_configuration_or_known_runtime_error(ValueError("test")) is True
    assert _is_configuration_or_known_runtime_error(KeyError("test")) is True
    assert _is_configuration_or_known_runtime_error(RuntimeError("test")) is True
    assert _is_configuration_or_known_runtime_error(json.JSONDecodeError("test", "", 0)) is True
    assert _is_configuration_or_known_runtime_error(OSError("test")) is True
    assert _is_configuration_or_known_runtime_error(Exception("test")) is False