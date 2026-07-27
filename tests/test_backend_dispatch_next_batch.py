import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.scratch.dispatch_next_batch import main
from backend.agents.orchestration.hub_common import OpusQuotaExceededException

def test_main_success(capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 30,
        "current_milestone": "M30.1"
    }
    mock_hub.get_next_batch.return_value = {
        "batch_id": "test_batch",
        "tasks": []
    }
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub):
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "BATCH_START" in captured.out
        assert "BATCH_END" in captured.out
        assert "test_batch" in captured.out

@pytest.mark.parametrize("exception_class", [
    ValueError, KeyError, OSError, json.JSONDecodeError, ImportError, RuntimeError, OpusQuotaExceededException
])
def test_main_expected_exceptions(exception_class, capsys):
    mock_hub = MagicMock()
    if exception_class == json.JSONDecodeError:
        err = json.JSONDecodeError("msg", "doc", 0)
    else:
        err = exception_class("test error")
        
    mock_hub.get_phase_state.side_effect = err
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub):
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert f"Error executing dispatch_next_batch: {exception_class.__name__}" in captured.err

@pytest.mark.parametrize("exception_class", [
    AttributeError, TypeError, IndexError, NameError, AssertionError
])
def test_main_unexpected_exceptions_register_debt(exception_class, capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.side_effect = exception_class("unexpected error")
    
    mock_store = MagicMock()
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
        code = main()
        assert code == 1
        mock_store.register_debt.assert_called_once()
        captured = capsys.readouterr()
        assert f"Unexpected error executing dispatch_next_batch: {exception_class.__name__}" in captured.err

def test_main_technical_debt_registration_fails(capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.side_effect = TypeError("unexpected error")
    
    mock_store = MagicMock()
    mock_store.register_debt.side_effect = OSError("Disk full")
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Disk full" in captured.err
        assert "Unexpected error executing dispatch_next_batch: TypeError" in captured.err


def test_main_batch_is_none(capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 30,
        "current_milestone": "M30.1"
    }
    mock_hub.get_next_batch.return_value = None
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub):
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "No batch returned.\n" in captured.err


def test_main_get_phase_state_invalid_type(capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = "not a dict"
    
    mock_store = MagicMock()
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
        code = main()
        assert code == 1
        mock_store.register_debt.assert_called_once()
        captured = capsys.readouterr()
        assert "Unexpected error executing dispatch_next_batch: TypeError" in captured.err


def test_main_get_phase_state_invalid_phase_type(capsys):
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": "not an int",
        "current_milestone": "M30.1"
    }
    
    mock_store = MagicMock()
    
    with patch("backend.scratch.dispatch_next_batch.OrchestrationHub", return_value=mock_hub), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
        code = main()
        assert code == 1
        mock_store.register_debt.assert_called_once()
        captured = capsys.readouterr()
        assert "Unexpected error executing dispatch_next_batch: TypeError" in captured.err
