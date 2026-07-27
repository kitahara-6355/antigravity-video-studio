"""tests/test_verify_council.py

Unit tests for verify_council.py.
"""
import sys
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# Add backend to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verify_council import run_council_simulation

@patch("verify_council.council_logger")
@patch("verify_council.run_council", new_callable=AsyncMock)
def test_run_council_simulation_success(mock_run_council, mock_logger, capsys):
    """Test run_council_simulation executes successfully with mock run_council."""
    mock_run_council.return_value = {
        "synthesis": "Test Synthesis Proposal Text",
        "session_id": "test-session-uuid-123",
        "status": "success"
    }
    mock_logger.log_session.return_value = "archives/council_logs/session_test.json"

    run_council_simulation()

    # run_council が正しく呼び出されているか
    mock_run_council.assert_called_once()
    args, kwargs = mock_run_council.call_args
    assert kwargs.get("user_query") == "Why is my channel growing so slowly?"
    assert kwargs.get("council_mode") == "post_production"
    assert "session_id" in kwargs

    # council_logger が正しく呼び出されているか
    mock_logger.log_session.assert_called_once()
    
    captured = capsys.readouterr()
    assert "--- 🏛️ THE COUNCIL OF MINDS: SIMULATION START ---" in captured.out
    assert "🗣️ User Query: 'Why is my channel growing so slowly?'" in captured.out
    assert "⚖️ Nexus Synthesis: \"Test Synthesis Proposal Text\"" in captured.out
    assert "✅ Simulation Complete. Log verified." in captured.out


@patch("verify_council.council_logger")
@patch("verify_council.run_council", new_callable=AsyncMock)
def test_run_council_simulation_failed_log(mock_run_council, mock_logger, capsys):
    """Test run_council_simulation output when logging fails."""
    mock_run_council.return_value = {
        "synthesis": "Test Synthesis Proposal Text",
        "session_id": "test-session-uuid-123",
        "status": "success"
    }
    mock_logger.log_session.return_value = None # logging failed

    run_council_simulation()

    captured = capsys.readouterr()
    assert "❌ Simulation Failed to log." in captured.out


def test_main_block_execution():
    """Test execution of the __main__ block using runpy to cover main script execution path."""
    import runpy
    
    mock_run_council = AsyncMock()
    mock_run_council.return_value = {
        "synthesis": "Block Synthesis Text",
        "session_id": "block-session-123",
        "status": "success"
    }
    
    with patch("agents.council_graph.run_council", mock_run_council):
        with patch("verify_council.council_logger.log_session", return_value="mock_log_path.json"):
            import os
            current_dir = os.path.dirname(__file__)
            target_path = os.path.abspath(os.path.join(current_dir, "..", "verify_council.py"))
            runpy.run_path(target_path, run_name="__main__")
            
            mock_run_council.assert_called_once()
