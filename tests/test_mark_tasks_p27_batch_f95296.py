# -*- coding: utf-8 -*-
import os
import sys
import runpy
from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path

# backend Dir sys.path add
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.agents.orchestration import mark_tasks_p27_batch_f95296

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "FLASH_STATUS_OK"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_f95296.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_batch_f95296.main()
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    # 6 tasks
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"formatted": "SCRIPT_OK"}
    
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_batch_f95296.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_batch_f95296.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    assert mock_hub_instance.mark_task_done.call_count == 6
