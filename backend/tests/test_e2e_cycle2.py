import pytest
from unittest.mock import patch, MagicMock, call
import urllib.request
import urllib.error
import json
import sys
import time
from tests import _e2e_cycle2

def mock_exit_func(code=0):
    raise SystemExit(code)

def test_wait_for_server_immediate_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        res = _e2e_cycle2.wait_for_server(timeout=5)
        assert res is True
        mock_urlopen.assert_called_once()

def test_wait_for_server_retry_then_success():
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep") as mock_sleep:
        # 1回目はエラー、2回目は成功
        mock_urlopen.side_effect = [urllib.error.URLError("connection refused"), MagicMock()]
        res = _e2e_cycle2.wait_for_server(timeout=5)
        assert res is True
        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once_with(2)

def test_wait_for_server_timeout():
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep") as mock_sleep:
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        res = _e2e_cycle2.wait_for_server(timeout=1)
        assert res is False
        assert mock_urlopen.call_count > 0

def test_check_dashboard_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"models": ["model1", "model2"]}'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.check_dashboard()
        assert res is True

def test_check_dashboard_url_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("error")
        res = _e2e_cycle2.check_dashboard()
        assert res is False

def test_check_dashboard_json_decode_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'invalid json'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.check_dashboard()
        assert res is False

def test_check_dashboard_type_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        # models がリストではなく int などで len() で TypeError を起こすケース
        mock_resp.read.return_value = b'{"models": 123}'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.check_dashboard()
        assert res is False

def test_start_pipeline():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"pipeline_id": "test_id"}'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.start_pipeline()
        assert res == {"pipeline_id": "test_id"}

def test_format_progress_message_with_running_stages():
    elapsed = 10
    status = "running"
    completed = 2
    running_stages = [{"name": "stage1", "detail": "processing video"}]
    
    msg = _e2e_cycle2._format_progress_message(elapsed, status, completed, running_stages)
    assert "stage1" in msg
    assert "processing video" in msg

def test_format_progress_message_no_running_stages():
    elapsed = 10
    status = "running"
    completed = 2
    running_stages = []
    
    msg = _e2e_cycle2._format_progress_message(elapsed, status, completed, running_stages)
    assert "stage1" not in msg

def test_monitor_pipeline_completed_immediately():
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep") as mock_sleep:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "completed", "stages": []}'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.monitor_pipeline(timeout=30)
        assert res == {"status": "completed", "stages": []}
        mock_sleep.assert_called_once_with(15)

def test_monitor_pipeline_polling_exceptions_then_completed():
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep") as mock_sleep:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "completed", "stages": []}'
        # 1回目はURLError, 2回目はKeyError, 3回目は成功
        mock_urlopen.side_effect = [
            urllib.error.URLError("network error"),
            MagicMock(read=MagicMock(return_value=b'{"invalid": "format"}')), # KeyErrorを起こす
            mock_resp
        ]
        
        res = _e2e_cycle2.monitor_pipeline(timeout=60)
        assert res == {"status": "completed", "stages": []}
        assert mock_sleep.call_count == 3

def test_monitor_pipeline_timeout():
    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("time.sleep") as mock_sleep:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "running", "stages": []}'
        mock_urlopen.return_value = mock_resp
        
        res = _e2e_cycle2.monitor_pipeline(timeout=5)
        # timeout=5 だが、sleep(15) が 1回走ると time.time() - start_time >= timeout になりループ抜ける
        assert res is None

def test_main_server_launch_fail():
    with patch("tests._e2e_cycle2.wait_for_server", return_value=False), \
         patch("sys.exit", side_effect=mock_exit_func):
        with pytest.raises(SystemExit) as excinfo:
            _e2e_cycle2.main()
        assert excinfo.value.code == 1

def test_main_success():
    with patch("tests._e2e_cycle2.wait_for_server", return_value=True), \
         patch("tests._e2e_cycle2.check_dashboard") as mock_check, \
         patch("tests._e2e_cycle2.start_pipeline", return_value={"id": "xyz"}) as mock_start, \
         patch("tests._e2e_cycle2.monitor_pipeline", return_value={"status": "completed"}) as mock_monitor, \
         patch("sys.exit") as mock_exit:
        
        _e2e_cycle2.main()
        mock_check.assert_called_once()
        mock_start.assert_called_once()
        mock_monitor.assert_called_once()
        mock_exit.assert_not_called()

def test_main_pipeline_error():
    with patch("tests._e2e_cycle2.wait_for_server", return_value=True), \
         patch("tests._e2e_cycle2.check_dashboard"), \
         patch("tests._e2e_cycle2.start_pipeline", return_value={"id": "xyz"}), \
         patch("tests._e2e_cycle2.monitor_pipeline", return_value={"status": "error"}), \
         patch("sys.exit", side_effect=mock_exit_func):
        
        with pytest.raises(SystemExit) as excinfo:
            _e2e_cycle2.main()
        assert excinfo.value.code == 1

def test_main_pipeline_timeout():
    with patch("tests._e2e_cycle2.wait_for_server", return_value=True), \
         patch("tests._e2e_cycle2.check_dashboard"), \
         patch("tests._e2e_cycle2.start_pipeline", return_value={"id": "xyz"}), \
         patch("tests._e2e_cycle2.monitor_pipeline", return_value=None), \
         patch("sys.exit", side_effect=mock_exit_func):
        
        with pytest.raises(SystemExit) as excinfo:
            _e2e_cycle2.main()
        assert excinfo.value.code == 1
