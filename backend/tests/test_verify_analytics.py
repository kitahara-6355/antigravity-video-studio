import sys
import os
import pytest
from unittest import mock
import requests

# ?????????????????????????
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

def test_verify_analytics_import_error():
    with mock.patch.dict("sys.modules", {"requests": None}):
        sys.modules.pop("backend.verify_analytics", None)
        with pytest.raises(SystemExit) as exc_info:
            import backend.verify_analytics
        assert exc_info.value.code == 1

def test_verify_analytics_success_all_elements(capsys):
    mock_res_get = mock.MagicMock()
    mock_res_get.json.return_value = {"ranks": {"biz_rank": {"xp": 100}}}
    
    mock_res_post = mock.MagicMock()
    mock_res_post.status_code = 200
    mock_res_post.json.return_value = {
        "simulation": "success",
        "sync": {
            "biz_xp": 120,
            "rivals": {
                "nemesis": {"name": "RivalA", "subs": 1000},
                "benchmark": {"name": "RivalB", "subs": 2000}
            },
            "quests": [
                {"type": "subs", "gap": 500, "reward_xp": 50}
            ]
        }
    }
    
    with mock.patch("requests.get", return_value=mock_res_get) as mock_get,          mock.patch("requests.post", return_value=mock_res_post) as mock_post:
        
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        backend.verify_analytics.verify()
        
        mock_get.assert_called_once_with("http://localhost:8000/api/status")
        mock_post.assert_called_once_with("http://localhost:8000/api/analytics/simulate?views=5000")
        
        captured = capsys.readouterr()
        assert "Initial Biz XP: 100" in captured.out
        assert "Simulation Result: success" in captured.out
        assert "Sync Result (Biz XP): 120" in captured.out
        assert "Nemesis Found: RivalA" in captured.out
        assert "Benchmark Found: RivalB" in captured.out
        assert "Active Quests: 1" in captured.out

def test_verify_analytics_success_empty_elements(capsys):
    mock_res_get = mock.MagicMock()
    mock_res_get.json.return_value = {}
    
    mock_res_post = mock.MagicMock()
    mock_res_post.status_code = 200
    mock_res_post.json.return_value = {
        "simulation": "success",
        "sync": {
            "biz_xp": 0,
            "rivals": {},
            "quests": []
        }
    }
    
    with mock.patch("requests.get", return_value=mock_res_get) as mock_get,          mock.patch("requests.post", return_value=mock_res_post) as mock_post:
        
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        backend.verify_analytics.verify()
        
        captured = capsys.readouterr()
        assert "Initial Biz XP: 0" in captured.out
        assert "Simulation Result: success" in captured.out
        assert "Sync Result (Biz XP): 0" in captured.out
        assert "Nemesis Found" not in captured.out
        assert "Benchmark Found" not in captured.out
        assert "Active Quests" not in captured.out

def test_verify_analytics_status_exception():
    with mock.patch("requests.get", side_effect=requests.exceptions.RequestException("Connection refused")):
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        with pytest.raises(SystemExit) as exc_info:
            backend.verify_analytics.verify()
        assert exc_info.value.code == 1

def test_verify_analytics_simulate_http_error(capsys):
    mock_res_get = mock.MagicMock()
    mock_res_get.json.return_value = {"ranks": {"biz_rank": {"xp": 10}}}
    
    mock_res_post = mock.MagicMock()
    mock_res_post.status_code = 500
    mock_res_post.text = "Internal Server Error"
    
    with mock.patch("requests.get", return_value=mock_res_get),          mock.patch("requests.post", return_value=mock_res_post):
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        backend.verify_analytics.verify()
        
        captured = capsys.readouterr()
        assert "Simulation Failed: 500 - Internal Server Error" in captured.out

def test_verify_analytics_simulate_exception(capsys):
    mock_res_get = mock.MagicMock()
    mock_res_get.json.return_value = {"ranks": {"biz_rank": {"xp": 10}}}
    
    with mock.patch("requests.get", return_value=mock_res_get),          mock.patch("requests.post", side_effect=requests.exceptions.RequestException("Timeout")):
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        backend.verify_analytics.verify()
        
        captured = capsys.readouterr()
        assert "Error during simulation: Timeout" in captured.out

def test_verify_analytics_main_execution():
    sys.modules.pop("backend.verify_analytics", None)
    
    with mock.patch("requests.get") as mock_get, mock.patch("requests.post") as mock_post:
        import runpy
        runpy.run_module("backend.verify_analytics", run_name="__main__")
        
        mock_get.assert_called_once()
        mock_post.assert_called_once()


def test_verify_analytics_with_testclient():
    from main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    from unittest import mock
    mock_branding_manager = mock.MagicMock()
    mock_branding_manager.user_model = {'ranks': {'biz_rank': {'xp': 100}}}
    mock_branding_manager.process_analytics_update.return_value = {
        'biz_xp': 120,
        'rivals': {
            'nemesis': {'name': 'RivalA', 'subs': 1000},
            'benchmark': {'name': 'RivalB', 'subs': 2000}
        },
        'quests': [
            {'type': 'subs', 'gap': 500, 'reward_xp': 50}
        ]
    }
    mock_analytics_manager = mock.MagicMock()
    mock_analytics_manager.sim_add_views.return_value = {'simulation': 'success'}
    with mock.patch('branding_manager.branding_manager', mock_branding_manager), \
         mock.patch('branding.analytics_manager.analytics_manager', mock_analytics_manager):
        res_get = client.get('/api/status')
        assert res_get.status_code == 200
        assert res_get.json() == mock_branding_manager.user_model
        res_post = client.post('/api/analytics/simulate?views=5000')
        assert res_post.status_code == 200
        data = res_post.json()
        assert 'simulation' in data
        assert 'sync' in data
        assert data['sync']['biz_xp'] == 120


def test_verify_analytics_custom_base_url():
    mock_res_get = mock.MagicMock()
    mock_res_get.json.return_value = {"ranks": {"biz_rank": {"xp": 100}}}
    
    mock_res_post = mock.MagicMock()
    mock_res_post.status_code = 200
    mock_res_post.json.return_value = {
        "simulation": "success",
        "sync": {
            "biz_xp": 120
        }
    }
    
    with mock.patch("requests.get", return_value=mock_res_get) as mock_get, \
         mock.patch("requests.post", return_value=mock_res_post) as mock_post:
        
        sys.modules.pop("backend.verify_analytics", None)
        import backend.verify_analytics
        
        custom_url = "http://custom-url:9000"
        backend.verify_analytics.verify(base_url=custom_url)
        
        mock_get.assert_called_once_with("http://custom-url:9000/api/status")
        mock_post.assert_called_once_with("http://custom-url:9000/api/analytics/simulate?views=5000")

