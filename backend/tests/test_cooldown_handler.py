import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pytest
import backend.agents.orchestration.cooldown_handler as cooldown_handler

def test_cooldown_handler_no_file():
    with patch("backend.agents.orchestration.cooldown_handler.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # Path.exists() が False を返すようにモック
        with patch.object(Path, "exists", return_value=False):
            cooldown_handler.main()
            mock_hub.flash_update_heartbeat.assert_called_once()

def test_cooldown_handler_read_error():
    with patch("backend.agents.orchestration.cooldown_handler.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        with patch.object(Path, "exists", return_value=True):
            # open で例外が発生するようにモック
            with patch("builtins.open", side_effect=Exception("Read error")):
                cooldown_handler.main()
                mock_hub.flash_update_heartbeat.assert_called_once()

def test_cooldown_handler_waiting():
    with patch("backend.agents.orchestration.cooldown_handler.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # 未来のリセット時刻を返す
        mock_data = {"reset_timestamp": time.time() + 100}
        # Path.exists が True を返すようにし、open でデータを返す
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
                cooldown_handler.main()
                mock_hub.flash_update_heartbeat.assert_called_once()

def test_cooldown_handler_finished():
    with patch("backend.agents.orchestration.cooldown_handler.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # 過去のリセット時刻を返す
        mock_data = {"reset_timestamp": time.time() - 100}
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
                with patch("os.remove") as mock_remove:
                    cooldown_handler.main()
                    mock_hub.flash_update_heartbeat.assert_called_once()
                    mock_remove.assert_called_once()

def test_cooldown_handler_remove_error():
    with patch("backend.agents.orchestration.cooldown_handler.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        mock_data = {"reset_timestamp": time.time() - 100}
        with patch.object(Path, "exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
                # os.remove が例外を発生させるが、握りつぶされることを確認
                with patch("os.remove", side_effect=OSError("Permission denied")):
                    cooldown_handler.main()
                    mock_hub.flash_update_heartbeat.assert_called_once()
