import sys
import pytest
from unittest.mock import MagicMock, patch
from backend.agents.orchestration.flash_get_next_batch import main

def test_flash_get_next_batch_success():
    with patch("backend.agents.orchestration.flash_get_next_batch.OrchestrationHub") as mock_hub_cls:
        mock_hub = MagicMock()
        mock_hub.get_next_batch.return_value = [{"task_id": "T-1", "status": "pending"}]
        mock_hub.generate_flash_status.return_value = {"formatted": "status-ok"}
        mock_hub_cls.return_value = mock_hub
        
        test_args = ["flash_get_next_batch.py", "--conversation-id", "dummy-id", "--phase", "33", "--milestone", "M33.1", "--batch-size", "5"]
        with patch.object(sys, "argv", test_args):
            main()
            
        mock_hub.register_flash_conversation_id.assert_called_once_with("dummy-id")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.get_next_batch.assert_called_once_with(phase=33, milestone="M33.1", batch_size=5)
        mock_hub.generate_flash_status.assert_called_once()

def test_flash_get_next_batch_exception_handling():
    with patch("backend.agents.orchestration.flash_get_next_batch.OrchestrationHub") as mock_hub_cls:
        mock_hub = MagicMock()
        mock_hub.flash_update_heartbeat.side_effect = OSError("Simulated OS Error")
        mock_hub_cls.return_value = mock_hub
        
        test_args = ["flash_get_next_batch.py", "--conversation-id", "dummy-id"]
        with patch.object(sys, "argv", test_args):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1

def test_flash_get_next_batch_generic_exception_handling():
    with patch("backend.agents.orchestration.flash_get_next_batch.OrchestrationHub") as mock_hub_cls:
        mock_hub = MagicMock()
        mock_hub.flash_update_heartbeat.side_effect = Exception("Simulated Generic Exception")
        mock_hub_cls.return_value = mock_hub
        
        test_args = ["flash_get_next_batch.py", "--conversation-id", "dummy-id"]
        with patch.object(sys, "argv", test_args):
            with pytest.raises(SystemExit) as excinfo:
                main()
            assert excinfo.value.code == 1
