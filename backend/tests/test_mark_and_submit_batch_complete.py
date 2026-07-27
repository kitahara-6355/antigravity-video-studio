import sys
import os
import json
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

@pytest.fixture(autouse=True)
def clean_modules():
    if "backend.agents.orchestration.mark_and_submit_batch_complete" in sys.modules:
        del sys.modules["backend.agents.orchestration.mark_and_submit_batch_complete"]

def test_mark_and_submit_batch_complete_success(capsys):
    mock_hub = MagicMock()
    dummy_status = {"status": "completed", "progress": 1.0}
    mock_hub.generate_flash_status.return_value = dummy_status

    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        assert result == 0

    mock_hub.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_63e89e",
        {
            "passed": 5,
            "failed": 1,
            "skipped": 0,
            "total": 6
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED_SUCCESSFULLY" in captured.out
    assert "FLASH_STATUS:" in captured.out
    assert '"status": "completed"' in captured.out

def test_submit_batch_results(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import submit_batch_results
    mock_hub = MagicMock()
    batch_id = "batch_test"
    batch_results = {"passed": 3, "failed": 0, "skipped": 0, "total": 3}

    submit_batch_results(mock_hub, batch_id, batch_results)

    mock_hub.submit_batch_report.assert_called_once_with(batch_id, batch_results)
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED_SUCCESSFULLY" in captured.out

def test_display_flash_status(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import display_flash_status
    mock_hub = MagicMock()
    dummy_status = {"status": "running", "progress": 0.8}
    mock_hub.generate_flash_status.return_value = dummy_status

    display_flash_status(mock_hub)

    mock_hub.generate_flash_status.assert_called_once()
    captured = capsys.readouterr()
    assert "FLASH_STATUS:" in captured.out
    assert '"status": "running"' in captured.out
    assert '"progress": 0.8' in captured.out


def test_submit_batch_results_exception(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import submit_batch_results
    mock_hub = MagicMock()
    mock_hub.submit_batch_report.side_effect = RuntimeError("Hub communication failed")
    
    with pytest.raises(RuntimeError) as exc_info:
        submit_batch_results(mock_hub, "batch_err", {"total": 0})
        
    assert "Hub communication failed" in str(exc_info.value)
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED_SUCCESSFULLY" not in captured.out

def test_submit_batch_results_index_error(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import submit_batch_results
    mock_hub = MagicMock()
    mock_hub.submit_batch_report.side_effect = IndexError("Index out of range")
    
    with pytest.raises(IndexError) as exc_info:
        submit_batch_results(mock_hub, "batch_err", {"total": 0})
        
    assert "Index out of range" in str(exc_info.value)
    captured = capsys.readouterr()
    assert "Error submitting batch results" in captured.err

def test_submit_batch_results_import_error(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import submit_batch_results
    mock_hub = MagicMock()
    mock_hub.submit_batch_report.side_effect = ImportError("Module not found")
    
    with pytest.raises(ImportError) as exc_info:
        submit_batch_results(mock_hub, "batch_err", {"total": 0})
        
    assert "Module not found" in str(exc_info.value)
    captured = capsys.readouterr()
    assert "Error submitting batch results" in captured.err

def test_display_flash_status_exception():
    from backend.agents.orchestration.mark_and_submit_batch_complete import display_flash_status
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = ValueError("Status not available")
    
    with pytest.raises(ValueError) as exc_info:
        display_flash_status(mock_hub)
        
    assert "Status not available" in str(exc_info.value)

def test_display_flash_status_index_error():
    from backend.agents.orchestration.mark_and_submit_batch_complete import display_flash_status
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = IndexError("Index error in status")
    
    with pytest.raises(IndexError) as exc_info:
        display_flash_status(mock_hub)
        
    assert "Index error in status" in str(exc_info.value)

def test_display_flash_status_import_error():
    from backend.agents.orchestration.mark_and_submit_batch_complete import display_flash_status
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = ImportError("Import error in status")
    
    with pytest.raises(ImportError) as exc_info:
        display_flash_status(mock_hub)
        
    assert "Import error in status" in str(exc_info.value)

def test_display_flash_status_serialization_error(capsys):
    from backend.agents.orchestration.mark_and_submit_batch_complete import display_flash_status
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"unserializable": object()}
    
    with pytest.raises(TypeError):
        display_flash_status(mock_hub)


def test_main_initialization_exception(capsys):
    """OrchestrationHubの初期化時または会話ID登録で例外が発生した場合に、sys.exit(1) で終了することを確認します。"""
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.register_flash_conversation_id.side_effect = RuntimeError("Init failed")
        
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Error initializing OrchestrationHub: Init failed" in captured.err

def test_main_initialization_index_error(capsys):
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.register_flash_conversation_id.side_effect = IndexError("Index error in init")
        
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Error initializing OrchestrationHub: Index error in init" in captured.err

def test_main_initialization_import_error(capsys):
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.register_flash_conversation_id.side_effect = ImportError("Import error in init")
        
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Error initializing OrchestrationHub: Import error in init" in captured.err


def test_main_submit_batch_exception_exit(capsys):
    """バッチ送信時に例外が発生した場合に、sys.exit(1) で終了することを確認します。"""
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.submit_batch_report.side_effect = ValueError("Submit failed")
        
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Error submitting batch results: Submit failed" in captured.err


def test_main_display_status_exception_exit(capsys):
    """ステータス表示時に例外が発生した場合に、sys.exit(1) で終了することを確認します。"""
    with patch("backend.agents.orchestration.mark_and_submit_batch_complete.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_class.return_value = mock_hub
        mock_hub.generate_flash_status.side_effect = RuntimeError("Status failed")
        
        from backend.agents.orchestration.mark_and_submit_batch_complete import main
        result = main()
        
        assert result == 1
        captured = capsys.readouterr()
        assert "Error generating flash status: Status failed" in captured.err
