# -*- coding: utf-8 -*-
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# バックエンドルートをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_and_update import (
    initialize_hub_and_session,
    mark_task_as_done,
    display_latest_flash_status,
    execute_default_update
)

def test_initialize_hub_and_session():
    mock_hub = MagicMock()
    with patch("agents.orchestration.mark_and_update.OrchestrationHub", return_value=mock_hub):
        hub = initialize_hub_and_session("test_conv_id")
        assert hub == mock_hub
        mock_hub.register_flash_conversation_id.assert_called_once_with("test_conv_id")
        mock_hub.flash_update_heartbeat.assert_called_once()

def test_mark_task_as_done(capsys):
    mock_hub = MagicMock()
    report = {"msg": "hello"}
    mark_task_as_done(mock_hub, "test_task_id", report)
    mock_hub.mark_task_done.assert_called_once_with("test_task_id", "pass", report)
    captured = capsys.readouterr()
    assert "TASK_MARKED_DONE" in captured.out

def test_display_latest_flash_status(capsys):
    mock_hub = MagicMock()
    mock_status = {"status": "ok"}
    mock_hub.generate_flash_status.return_value = mock_status
    
    display_latest_flash_status(mock_hub)
    mock_hub.generate_flash_status.assert_called_once()
    captured = capsys.readouterr()
    assert "FLASH_STATUS:" in captured.out
    status_data = json.loads(captured.out.replace("FLASH_STATUS:", "").strip())
    assert status_data == mock_status

def test_execute_default_update():
    mock_hub = MagicMock()
    with patch("agents.orchestration.mark_and_update.initialize_hub_and_session", return_value=mock_hub) as mock_init, \
         patch("agents.orchestration.mark_and_update.mark_task_as_done") as mock_mark, \
         patch("agents.orchestration.mark_and_update.display_latest_flash_status") as mock_display:
         
        execute_default_update()
        
        mock_init.assert_called_once_with("c34fe890-df08-40c8-bcda-07b5485dbe94")
        mock_mark.assert_called_once()
        args, _ = mock_mark.call_args
        assert args[0] == mock_hub
        assert args[1] == "T-batch_05cb80-bug_hunter-000"
        assert args[2]["changed_files"] == [
            "backend/combined_overlay.py",
            "backend/tests/test_combined_overlay.py"
        ]
        mock_display.assert_called_once_with(mock_hub)
