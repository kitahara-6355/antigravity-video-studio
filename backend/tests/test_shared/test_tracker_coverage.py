import pytest
import json
import sys
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, date

from usage_tracker.tracker import (
    UsageRecord,
    DailyUsage,
    UsageTracker,
    _load_model_config,
    MODEL_CONFIG_PATH
)

def test_usage_record_init():
    record = UsageRecord(model="gemini-3.6-flash", requests=5, tokens_in=100, tokens_out=200)
    assert record.model == "gemini-3.6-flash"
    assert record.requests == 5
    assert record.tokens_in == 100
    assert record.tokens_out == 200
    assert record.timestamp is not None

def test_daily_usage_methods():
    du = DailyUsage(date="2026-05-27")
    assert du.date == "2026-05-27"
    assert du.get_requests("model-a") == 0
    
    du.add_request("model-a", tokens_in=10, tokens_out=20)
    assert du.get_requests("model-a") == 1
    assert du.models["model-a"]["tokens_in"] == 10
    assert du.models["model-a"]["tokens_out"] == 20
    
    du.add_request("model-a", tokens_in=5, tokens_out=5)
    assert du.get_requests("model-a") == 2
    assert du.models["model-a"]["tokens_in"] == 15
    assert du.models["model-a"]["tokens_out"] == 25

def test_load_model_config_failure():
    with patch("usage_tracker.tracker.MODEL_CONFIG_PATH", Path("non_existent_config.json")):
        res = _load_model_config()
        assert res == {}

def test_load_model_config_os_error():
    with patch("builtins.open", side_effect=OSError("Disk failure")):
        res = _load_model_config()
        assert res == {}

def test_tracker_init_and_config(tmp_path):
    mock_config = {
        "free_tier_limits": {
            "gemini-3.6-flash": {"rpd": 100, "tier": "free"}
        },
        "alert_thresholds": {
            "warning": 0.75
        }
    }
    
    usage_file = tmp_path / "usage_data.json"
    
    with patch("usage_tracker.tracker.MODEL_CONFIG_PATH", Path("non_existent.json")):
        with patch("usage_tracker.tracker.UsageTracker._save_usage") as mock_save:
            tracker = UsageTracker()
            tracker._usage_path = usage_file
            tracker._daily_usage = DailyUsage(date=date.today().isoformat())
            assert tracker._free_tier_limits == {}
            
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        tracker = UsageTracker()
        tracker._usage_path = usage_file
        tracker._daily_usage = DailyUsage(date=date.today().isoformat())
        assert tracker._free_tier_limits == mock_config["free_tier_limits"]
        assert tracker._alert_thresholds["warning"] == 0.75

def test_tracker_get_rpd_default():
    tracker = UsageTracker()
    assert tracker._get_rpd("unknown-model") == 1000

def test_load_or_create_daily_usage_exists(tmp_path):
    today = date.today().isoformat()
    usage_file = tmp_path / "usage_data.json"
    
    usage_data = {
        "date": today,
        "models": {
            "gemini-3.6-flash": {"requests": 5, "tokens_in": 50, "tokens_out": 50}
        }
    }
    with open(usage_file, "w", encoding="utf-8") as f:
        json.dump(usage_data, f)
        
    tracker = UsageTracker()
    tracker._usage_path = usage_file
    tracker._load_or_create_daily_usage()
    
    assert tracker._daily_usage.date == today
    assert tracker._daily_usage.get_requests("gemini-3.6-flash") == 5

def test_load_or_create_daily_usage_corrupt(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    with open(usage_file, "w", encoding="utf-8") as f:
        f.write("{invalid json")
        
    tracker = UsageTracker()
    tracker._usage_path = usage_file
    tracker._load_or_create_daily_usage()
    
    assert tracker._daily_usage.date == date.today().isoformat()

def test_load_or_create_daily_usage_os_error(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    
    tracker = UsageTracker()
    tracker._usage_path = usage_file
    
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", side_effect=OSError("Read error")):
            tracker._load_or_create_daily_usage()
            
    assert tracker._daily_usage.date == date.today().isoformat()

def test_save_usage_type_error(tmp_path):
    # **相対パスを書かない。** `Path("dummy.json")` は CWD に実ファイルを作り、
    # リポジトリ直下に空の `dummy.json` が残っていた（2026-08-27 に追跡下へ
    # 紛れ込んだ）。汚染ラチェットが検出する。
    tracker = UsageTracker()
    tracker._usage_path = tmp_path / "dummy.json"
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    
    with patch("json.dump", side_effect=TypeError("Not serializable")):
        tracker._save_usage()

def test_save_usage_failure(tmp_path):
    tracker = UsageTracker()
    tracker._usage_path = Path("/invalid_dir/invalid_file.json")
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    tracker._save_usage()

def test_track_request_normal(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    
    mock_config = {
        "free_tier_limits": {
            "gemini-3.6-flash": {"rpd": 10, "tier": "free"}
        }
    }
    
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        tracker = UsageTracker()
        tracker._usage_path = usage_file
        tracker._daily_usage = DailyUsage(date=date.today().isoformat())
        
        mock_callback = MagicMock()
        tracker.register_alert_callback(mock_callback)
        
        res = tracker.track_request("gemini-3.6-flash", tokens_in=10, tokens_out=20)
        assert res["requests_today"] == 1
        assert res["usage_ratio"] == 0.1
        assert res["alert_level"] == "normal"
        assert res["blocked"] is False
        mock_callback.assert_called_once()
        
        tracker._daily_usage.date = "2020-01-01"
        res = tracker.track_request("gemini-3.6-flash", tokens_in=5, tokens_out=5)
        assert res["requests_today"] == 1

def test_track_request_callback_exception():
    tracker = UsageTracker()
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    
    bad_callback = MagicMock(side_effect=Exception("Callback failed"))
    tracker.register_alert_callback(bad_callback)
    
    res = tracker.track_request("gemini-3.6-flash")
    assert res is not None

def test_alert_levels(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    mock_config = {
        "free_tier_limits": {
            "gemini-3.6-flash": {"rpd": 100, "tier": "free"}
        }
    }
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        tracker = UsageTracker()
        tracker._usage_path = usage_file
        tracker._daily_usage = DailyUsage(date=date.today().isoformat())
        
        # 60% info
        for _ in range(59):
            tracker.track_request("gemini-3.6-flash")
        res = tracker.track_request("gemini-3.6-flash")
        assert res["alert_level"] == "info"
        
        # 80% warning
        for _ in range(19):
            tracker.track_request("gemini-3.6-flash")
        res = tracker.track_request("gemini-3.6-flash")
        assert res["alert_level"] == "warning"
        
        # 95% block
        for _ in range(14):
            tracker.track_request("gemini-3.6-flash")
        res = tracker.track_request("gemini-3.6-flash")
        assert res["alert_level"] == "block"
        assert res["blocked"] is False
        
        # 100% critical
        for _ in range(4):
            tracker.track_request("gemini-3.6-flash")
        res = tracker.track_request("gemini-3.6-flash")
        assert res["alert_level"] == "critical"
        assert res["blocked"] is True

def test_can_make_request():
    tracker = UsageTracker()
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    assert tracker.can_make_request("gemini-3.6-flash") is True
    
    tracker._daily_usage.models["gemini-3.6-flash"] = {"requests": 1000, "tokens_in": 0, "tokens_out": 0}
    assert tracker.can_make_request("gemini-3.6-flash") is False

def test_get_remaining_requests():
    tracker = UsageTracker()
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    tracker._daily_usage.models["gemini-3.6-flash"] = {"requests": 350, "tokens_in": 0, "tokens_out": 0}
    assert tracker.get_remaining_requests("gemini-3.6-flash") == 650

def test_get_daily_summary():
    mock_config = {
        "free_tier_limits": {
            "gemini-3.6-flash": {"rpd": 100, "tier": "free"},
            "gemini-2.5-pro": {"rpd": 0, "tier": "pro"},
        }
    }
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        tracker = UsageTracker()
        tracker._daily_usage = DailyUsage(date=date.today().isoformat())
        tracker._daily_usage.models["gemini-3.6-flash"] = {"requests": 40, "tokens_in": 10, "tokens_out": 20}
        summary = tracker.get_daily_summary()
        
        assert "gemini-3.6-flash" in summary["models"]
        assert "gemini-2.5-pro" not in summary["models"]
        assert summary["models"]["gemini-3.6-flash"]["used"] == 40
        assert summary["models"]["gemini-3.6-flash"]["limit"] == 100

def test_get_model_recommendation_import_error():
    tracker = UsageTracker()
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    
    with patch.dict("sys.modules", {"model_registry": None}):
        rec = tracker.get_model_recommendation("transcription")
        assert rec == "gemini-3.6-flash"

def test_get_model_recommendation_registry_exception():
    tracker = UsageTracker()
    tracker._daily_usage = DailyUsage(date=date.today().isoformat())
    
    mock_registry = MagicMock()
    mock_registry.get_model.side_effect = RuntimeError("Registry crash")
    
    with patch.dict("sys.modules", {"model_registry": mock_registry}):
        rec = tracker.get_model_recommendation("transcription")
        assert rec == "gemini-3.6-flash"

def test_get_model_recommendation_fallback_chain(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    mock_config = {
        "free_tier_limits": {
            "gemini-2.5-pro": {"rpd": 10, "tier": "pro"},
            "gemini-3.6-flash": {"rpd": 100, "tier": "free"}
        },
        "text_generation": {
            "fallback_chain": {
                "gemini-2.5-pro": "gemini-3.6-flash"
            }
        }
    }
    
    mock_registry = MagicMock()
    mock_registry.get_model.return_value = "gemini-2.5-pro"
    
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        with patch.dict("sys.modules", {"model_registry": mock_registry}):
            tracker = UsageTracker()
            tracker._usage_path = usage_file
            tracker._daily_usage = DailyUsage(date=date.today().isoformat())
            
            rec = tracker.get_model_recommendation("text")
            assert rec == "gemini-2.5-pro"
            
            tracker._daily_usage.models["gemini-2.5-pro"] = {"requests": 10, "tokens_in": 0, "tokens_out": 0}
            
            rec = tracker.get_model_recommendation("text")
            assert rec == "gemini-3.6-flash"

def test_get_model_recommendation_image_fallback(tmp_path):
    usage_file = tmp_path / "usage_data.json"
    mock_config = {
        "free_tier_limits": {
            "imagen-4.0-ultra-generate-001": {"rpd": 10, "tier": "premium"},
            "imagen-4.0-generate-001": {"rpd": 100, "tier": "standard"}
        },
        "image_generation": {
            "fallback_chain": {
                "imagen-4.0-ultra-generate-001": "imagen-4.0-generate-001"
            }
        }
    }
    
    mock_registry = MagicMock()
    mock_registry.get_model.return_value = "imagen-4.0-ultra-generate-001"
    
    with patch("usage_tracker.tracker._load_model_config", return_value=mock_config):
        with patch.dict("sys.modules", {"model_registry": mock_registry}):
            tracker = UsageTracker()
            tracker._usage_path = usage_file
            tracker._daily_usage = DailyUsage(date=date.today().isoformat())
            
            rec = tracker.get_model_recommendation("thumbnail")
            assert rec == "imagen-4.0-ultra-generate-001"
            
            tracker._daily_usage.models["imagen-4.0-ultra-generate-001"] = {"requests": 10, "tokens_in": 0, "tokens_out": 0}
            
            rec = tracker.get_model_recommendation("thumbnail")
            assert rec == "imagen-4.0-generate-001"
