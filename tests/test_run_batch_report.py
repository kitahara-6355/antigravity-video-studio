import sys
import os
import json
from unittest.mock import MagicMock, patch
import pytest

# テスト対象のインポートができるようにパス調整
sys.path.append(os.path.abspath("backend/agents/orchestration"))
import run_batch_report

def test_run_batch_report_success(capsys):
    with patch("run_batch_report.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        run_batch_report.main()
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.submit_batch_report.assert_called_once_with(
            'batch_43915c', {'passed': 6, 'failed': 0, 'skipped': 0, 'total': 6}
        )
        mock_hub.generate_flash_status.assert_called_once()
        
        captured = capsys.readouterr()
        assert "STATUS_START" in captured.out
        assert "STATUS_END" in captured.out
        assert '{"status": "ok"}' in captured.out

def test_run_batch_report_value_error(capsys):
    with patch("run_batch_report.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.submit_batch_report.side_effect = ValueError("invalid value")
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        run_batch_report.main()
        
        captured = capsys.readouterr()
        assert "Validation error: invalid value" in captured.out

def test_run_batch_report_os_error(capsys):
    with patch("run_batch_report.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.submit_batch_report.side_effect = OSError("disk full")
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        run_batch_report.main()
        
        captured = capsys.readouterr()
        assert "I/O error during submit: disk full" in captured.out

def test_run_batch_report_format_error(capsys):
    with patch("run_batch_report.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.submit_batch_report.side_effect = KeyError("missing key")
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        run_batch_report.main()
        
        captured = capsys.readouterr()
        assert "Data format error: 'missing key'" in captured.out
