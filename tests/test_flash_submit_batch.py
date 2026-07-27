import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@pytest.fixture(autouse=True)
def clean_modules():
    if "backend.agents.orchestration.flash_submit_batch" in sys.modules:
        del sys.modules["backend.agents.orchestration.flash_submit_batch"]

def test_flash_submit_batch_success(capsys):
    queue_data = {
        "current_batch_id": "batch_test_123",
        "tasks": [
            {"id": "t1", "status": "pass"},
            {"id": "t2", "status": "fail"},
            {"id": "t3", "status": "skip"},
            {"id": "t4", "status": "skipped"},
            {"id": "t5", "status": "unknown"}
        ]
    }
    
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "Mock Status Text"}

    from unittest.mock import mock_open
    m_open = mock_open(read_data=json.dumps(queue_data))

    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=True),          patch("backend.agents.orchestration.flash_submit_batch.open", m_open):
         
        mock_args.return_value = MagicMock(conversation_id="test-conv-id-123")
        
        from backend.agents.orchestration.flash_submit_batch import main
        main()
        
    mock_hub.register_flash_conversation_id.assert_called_once_with("test-conv-id-123")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_test_123",
        {
            "passed": 1,
            "failed": 1,
            "skipped": 2,
            "total": 5
        }
    )
    captured = capsys.readouterr()
    assert "Submitting batch batch_test_123: passed=1, failed=1, skipped=2, total=5" in captured.out
    assert "Mock Status Text" in captured.out

def test_flash_submit_batch_env_var(capsys):
    queue_data = {
        "current_batch_id": "batch_test_123",
        "tasks": []
    }
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"formatted": "Status"}
    
    from unittest.mock import mock_open
    m_open = mock_open(read_data=json.dumps(queue_data))

    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=True),          patch("backend.agents.orchestration.flash_submit_batch.open", m_open),          patch.dict(os.environ, {"FLASH_CONVERSATION_ID": "env-conv-id"}):
         
        mock_args.return_value = MagicMock(conversation_id=None)
        
        from backend.agents.orchestration.flash_submit_batch import main
        main()
        
    mock_hub.register_flash_conversation_id.assert_called_once_with("env-conv-id")

def test_flash_submit_batch_session_fallback(capsys):
    queue_data = {"current_batch_id": "batch_test_123", "tasks": []}
    mock_hub = MagicMock()
    mock_hub.get_flash_session.return_value = {"conversation_id": "session-conv-id"}
    mock_hub.generate_flash_status.return_value = {"formatted": "Status"}
    
    from unittest.mock import mock_open
    m_open = mock_open(read_data=json.dumps(queue_data))

    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=True),          patch("backend.agents.orchestration.flash_submit_batch.open", m_open),          patch.dict(os.environ, {}, clear=True):
         
        mock_args.return_value = MagicMock(conversation_id=None)
        
        from backend.agents.orchestration.flash_submit_batch import main
        main()
        
    mock_hub.register_flash_conversation_id.assert_called_once_with("session-conv-id")

def test_flash_submit_batch_session_exception_fallback(capsys):
    queue_data = {"current_batch_id": "batch_test_123", "tasks": []}
    mock_hub = MagicMock()
    mock_hub.get_flash_session.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mock_hub.generate_flash_status.return_value = {"formatted": "Status"}
    
    from unittest.mock import mock_open
    m_open = mock_open(read_data=json.dumps(queue_data))

    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=True),          patch("backend.agents.orchestration.flash_submit_batch.open", m_open),          patch.dict(os.environ, {}, clear=True):
         
        mock_args.return_value = MagicMock(conversation_id=None)
        
        from backend.agents.orchestration.flash_submit_batch import main
        main()
        
    mock_hub.register_flash_conversation_id.assert_called_once_with("846cd96f-9aaa-41f7-b29e-ece50b846de9")

def test_flash_submit_batch_file_not_found(capsys):
    mock_hub = MagicMock()
    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=False):
         
        mock_args.return_value = MagicMock(conversation_id="conv-id")
        
        from backend.agents.orchestration.flash_submit_batch import main
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error: backend/agents/orchestration/task_queue.json not found." in captured.err

def test_flash_submit_batch_json_decode_error(capsys):
    mock_hub = MagicMock()
    from unittest.mock import mock_open
    m_open = mock_open(read_data="invalid json")

    with patch("backend.agents.orchestration.flash_submit_batch.OrchestrationHub", return_value=mock_hub),          patch("backend.agents.orchestration.flash_submit_batch.argparse.ArgumentParser.parse_args") as mock_args,          patch("backend.agents.orchestration.flash_submit_batch.os.path.exists", return_value=True),          patch("backend.agents.orchestration.flash_submit_batch.open", m_open):
         
        mock_args.return_value = MagicMock(conversation_id="conv-id")
        
        from backend.agents.orchestration.flash_submit_batch import main
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Error reading or parsing backend/agents/orchestration/task_queue.json" in captured.err
