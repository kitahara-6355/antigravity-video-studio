import pytest
from unittest.mock import patch, MagicMock
import urllib.request
import json
import sys

# テスト対象モジュールのインポート
from tests import _e2e_cycle2

def test_wait_for_server_success():
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        res = _e2e_cycle2.wait_for_server(timeout=2)
        assert res is True
        mock_urlopen.assert_called_once_with(f"{_e2e_cycle2.API}/api/pipeline/status", timeout=3)

def test_wait_for_server_timeout():
    with patch('urllib.request.urlopen') as mock_urlopen,          patch('time.sleep') as mock_sleep:
        mock_urlopen.side_effect = Exception("Connection refused")
        res = _e2e_cycle2.wait_for_server(timeout=1)
        assert res is False
        assert mock_urlopen.call_count > 0

def test_check_dashboard_success():
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"models": ["model1", "model2"]}).encode('utf-8')
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.check_dashboard()
        assert res is True

def test_check_dashboard_failure():
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.side_effect = Exception("HTTP 500")
        res = _e2e_cycle2.check_dashboard()
        assert res is False

def test_start_pipeline():
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "started"}).encode('utf-8')
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.start_pipeline()
        assert res == {"status": "started"}

def test_monitor_pipeline_completed():
    with patch('urllib.request.urlopen') as mock_urlopen,          patch('time.sleep') as mock_sleep:
        
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "completed",
            "stages": [
                {"name": "stage1", "status": "completed"},
                {"name": "stage2", "status": "running", "detail": "processing video"}
            ]
        }).encode('utf-8')
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.monitor_pipeline(timeout=60)
        assert res["status"] == "completed"

def test_monitor_pipeline_error():
    with patch('urllib.request.urlopen') as mock_urlopen,          patch('time.sleep') as mock_sleep:
        
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "status": "error",
            "stages": []
        }).encode('utf-8')
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.monitor_pipeline(timeout=60)
        assert res["status"] == "error"

def test_monitor_pipeline_exception_then_timeout():
    with patch('urllib.request.urlopen') as mock_urlopen,          patch('time.sleep') as mock_sleep,          patch('time.time') as mock_time:
        
        mock_urlopen.side_effect = Exception("Connection error")
        mock_time.side_effect = [100.0, 100.0, 100.0, 200.0, 200.0]
        
        res = _e2e_cycle2.monitor_pipeline(timeout=50)
        assert res is None

def test_main_success():
    with patch('tests._e2e_cycle2.wait_for_server') as mock_wait,          patch('tests._e2e_cycle2.check_dashboard') as mock_check,          patch('tests._e2e_cycle2.start_pipeline') as mock_start,          patch('tests._e2e_cycle2.monitor_pipeline') as mock_monitor:
        
        mock_wait.return_value = True
        mock_check.return_value = True
        mock_start.return_value = {"status": "started"}
        mock_monitor.return_value = {"status": "completed"}
        
        _e2e_cycle2.main()

def test_main_server_fail():
    with patch('tests._e2e_cycle2.wait_for_server') as mock_wait:
        mock_wait.return_value = False
        with pytest.raises(SystemExit) as exc_info:
            _e2e_cycle2.main()
        assert exc_info.value.code == 1

def test_main_pipeline_error():
    with patch('tests._e2e_cycle2.wait_for_server') as mock_wait,          patch('tests._e2e_cycle2.check_dashboard') as mock_check,          patch('tests._e2e_cycle2.start_pipeline') as mock_start,          patch('tests._e2e_cycle2.monitor_pipeline') as mock_monitor:
        
        mock_wait.return_value = True
        mock_check.return_value = True
        mock_start.return_value = {"status": "started"}
        mock_monitor.return_value = {"status": "error"}
        
        with pytest.raises(SystemExit) as exc_info:
            _e2e_cycle2.main()
        assert exc_info.value.code == 1

def test_main_pipeline_timeout():
    with patch('tests._e2e_cycle2.wait_for_server') as mock_wait,          patch('tests._e2e_cycle2.check_dashboard') as mock_check,          patch('tests._e2e_cycle2.start_pipeline') as mock_start,          patch('tests._e2e_cycle2.monitor_pipeline') as mock_monitor:
        
        mock_wait.return_value = True
        mock_check.return_value = True
        mock_start.return_value = {"status": "started"}
        mock_monitor.return_value = None
        
        with pytest.raises(SystemExit) as exc_info:
            _e2e_cycle2.main()
        assert exc_info.value.code == 1


def test_monitor_pipeline_running_then_completed():
    with patch('urllib.request.urlopen') as mock_urlopen, \
         patch('time.sleep') as mock_sleep, \
         patch('time.time') as mock_time:
         
        mock_time.side_effect = [100.0, 100.0, 100.0, 115.0, 115.0, 115.0, 130.0]
        
        mock_resp_running = MagicMock()
        mock_resp_running.read.return_value = json.dumps({
            "status": "running",
            "stages": [
                {"name": "stage1", "status": "completed"},
                {"name": "stage2", "status": "running", "detail": "processing"}
            ]
        }).encode('utf-8')
        
        mock_resp_completed = MagicMock()
        mock_resp_completed.read.return_value = json.dumps({
            "status": "completed",
            "stages": [
                {"name": "stage1", "status": "completed"},
                {"name": "stage2", "status": "completed"}
            ]
        }).encode('utf-8')
        
        mock_urlopen.side_effect = [mock_resp_running, mock_resp_completed]
        
        res = _e2e_cycle2.monitor_pipeline(timeout=60)
        assert res["status"] == "completed"
        assert mock_urlopen.call_count == 2
        assert mock_sleep.call_count == 2
