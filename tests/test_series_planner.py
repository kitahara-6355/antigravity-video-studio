"""
Unit tests for backend/services/series_planner.py
"""
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure backend path is in sys.path
backend_path = str(Path(__file__).parent.parent / "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

@pytest.fixture
def fresh_series_planner(tmp_path):
    """
    Creates a fresh SeriesPlanner instance using a temporary directory for BRANDING_DIR.
    """
    import safe_io
    original_branding_dir = safe_io.BRANDING_DIR
    safe_io.BRANDING_DIR = tmp_path
    
    # Force reload of services.series_planner to initialize with the new BRANDING_DIR
    if "services.series_planner" in sys.modules:
        del sys.modules["services.series_planner"]
        
    from services.series_planner import SeriesPlanner
    planner = SeriesPlanner()
    
    yield planner
    
    # Restore branding dir
    safe_io.BRANDING_DIR = original_branding_dir

def test_register_series_success(fresh_series_planner):
    planner = fresh_series_planner
    res = planner.register_series("series_1", "Series Title 1", "Theme 1", "Target Persona 1")
    
    assert res["title"] == "Series Title 1"
    assert res["theme"] == "Theme 1"
    assert res["target_persona"] == "Target Persona 1"
    assert "created_at" in res
    assert res["videos"] == []
    assert res["playlist_url"] == ""

    # Check store has persisted the data
    loaded = planner._load()
    assert "series_1" in loaded["series"]
    assert loaded["series"]["series_1"]["title"] == "Series Title 1"

def test_register_series_duplicate(fresh_series_planner, caplog):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1", "Target Persona 1")
    
    # Try duplicate registration
    res = planner.register_series("series_1", "Series Title 2", "Theme 2", "Target Persona 2")
    assert res["title"] == "Series Title 1"  # Returns original series
    assert any("シリーズ 'series_1' はすでに登録されています。" in record.message for record in caplog.records)

def test_register_series_missing_series_key(fresh_series_planner):
    planner = fresh_series_planner
    # Write a file without the "series" key to test the missing key edge case
    import json
    with open(planner._store.path, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "description": "Test"}, f)
    
    res = planner.register_series("series_1", "Series Title 1", "Theme 1")
    assert "series" in planner.series_data
    assert "series_1" in planner.series_data["series"]

def test_add_video_to_series_success(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    
    success = planner.add_video_to_series("series_1", "video_100", "Video 100 Title")
    assert success is True
    
    # Duplicate addition (should skip but return True)
    success_duplicate = planner.add_video_to_series("series_1", "video_100", "Video 100 Title")
    assert success_duplicate is True
    
    # Verify records
    loaded = planner._load()
    videos = loaded["series"]["series_1"]["videos"]
    assert len(videos) == 1
    assert videos[0]["video_id"] == "video_100"
    assert videos[0]["title"] == "Video 100 Title"

def test_add_video_to_series_nonexistent(fresh_series_planner, caplog):
    planner = fresh_series_planner
    success = planner.add_video_to_series("nonexistent_series", "video_100", "Title")
    assert success is False
    assert any("シリーズ 'nonexistent_series' が見つかりません。" in record.message for record in caplog.records)

def test_suggest_next_video_success(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    
    res = planner.suggest_next_video("series_1", "video_100", "some context")
    assert res["success"] is True
    assert res["series_id"] == "series_1"
    assert res["current_video_id"] == "video_100"
    assert "Theme 1" in res["teaser_text"]
    assert "visual_recommendation" in res["cta_suggestion"]
    assert "audio_recommendation" in res["cta_suggestion"]

def test_suggest_next_video_nonexistent(fresh_series_planner):
    planner = fresh_series_planner
    res = planner.suggest_next_video("nonexistent_series", "video_100", "some context")
    assert res["success"] is False
    assert "nonexistent_series" in res["message"]
    assert "チャンネル登録と高評価をお願いします！" in res["teaser_text"]

def test_optimize_playlist_nonexistent(fresh_series_planner):
    planner = fresh_series_planner
    res = planner.optimize_playlist("nonexistent_series")
    assert res["success"] is False
    assert "nonexistent_series" in res["message"]

def test_optimize_playlist_no_videos(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    
    res = planner.optimize_playlist("series_1")
    assert res["success"] is False
    assert "このシリーズにはまだ動画が登録されていません。" in res["message"]

def test_optimize_playlist_one_video(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    planner.add_video_to_series("series_1", "video_1", "Video 1")
    
    res = planner.optimize_playlist("series_1")
    assert res["success"] is True
    assert "これはシリーズ第一作目です。" in res["overall_message"]
    assert "チャンネル登録ボタン ＋ 最新のアップロード動画" in res["end_screen_recommendation"]

def test_optimize_playlist_two_videos(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    planner.add_video_to_series("series_1", "video_1", "Video 1")
    planner.add_video_to_series("series_1", "video_2", "Video 2")
    
    res = planner.optimize_playlist("series_1")
    assert res["success"] is True
    assert res["video_count"] == 2
    assert res["suggested_order"] == ["video_1", "video_2"]
    assert "左: 前回の動画 / 右: チャンネル登録" in res["end_screen_recommendation"]

def test_optimize_playlist_three_or_more_videos(fresh_series_planner):
    planner = fresh_series_planner
    planner.register_series("series_1", "Series Title 1", "Theme 1")
    planner.add_video_to_series("series_1", "video_1", "Video 1")
    planner.add_video_to_series("series_1", "video_2", "Video 2")
    planner.add_video_to_series("series_1", "video_3", "Video 3")
    
    res = planner.optimize_playlist("series_1")
    assert res["success"] is True
    assert res["video_count"] == 3
    assert "左: シリーズ第1回('Video 1')の復習 / 右: チャンネル登録" in res["end_screen_recommendation"]
