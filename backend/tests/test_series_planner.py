# -*- coding: utf-8 -*-
import pytest
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.series_planner import SeriesPlanner, series_planner

@pytest.fixture
def temp_registry_file(tmp_path):
    test_file = tmp_path / "series_registry.json"
    return test_file

def test_series_planner_init_and_load(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        assert planner.series_data == {"version": "1.0", "description": "YouTube Series and Continuity Registry", "series": {}}

def test_register_series_success(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        res = planner.register_series("series_1", "Series Title", "Series Theme", "Persona A")
        assert res["title"] == "Series Title"
        assert res["theme"] == "Series Theme"
        assert res["target_persona"] == "Persona A"
        assert len(res["videos"]) == 0
        
        res2 = planner.register_series("series_1", "New Title", "New Theme")
        assert res2["title"] == "Series Title"

def test_register_series_schema_fix(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        planner.series_data = {}
        planner._save()
        
        res = planner.register_series("series_1", "Title", "Theme")
        assert "series" in planner.series_data
        assert "series_1" in planner.series_data["series"]

def test_add_video_to_series(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        
        assert planner.add_video_to_series("nonexistent", "vid_1", "Vid Title") is False
        
        planner.register_series("series_1", "Title", "Theme")
        assert planner.add_video_to_series("series_1", "vid_1", "Vid Title 1") is True
        
        assert planner.add_video_to_series("series_1", "vid_1", "Vid Title 1") is True
        
        assert planner.add_video_to_series("series_1", "vid_2", "Vid Title 2") is True

def test_suggest_next_video(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        
        res = planner.suggest_next_video("nonexistent", "vid_1", "context")
        assert res["success"] is False
        assert "teaser_text" in res
        
        planner.register_series("series_1", "Title", "Theme")
        res2 = planner.suggest_next_video("series_1", "vid_1", "context")
        assert res2["success"] is True
        assert "Theme" in res2["teaser_text"]
        assert "cta_suggestion" in res2

def test_optimize_playlist(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        
        res = planner.optimize_playlist("nonexistent")
        assert res["success"] is False
        
        planner.register_series("series_1", "Title", "Theme")
        
        res0 = planner.optimize_playlist("series_1")
        assert res0["success"] is False
        
        planner.add_video_to_series("series_1", "vid_1", "Vid 1")
        res1 = planner.optimize_playlist("series_1")
        assert res1["success"] is True
        assert "第一作目" in res1["overall_message"]
        
        planner.add_video_to_series("series_1", "vid_2", "Vid 2")
        res2 = planner.optimize_playlist("series_1")
        assert res2["success"] is True
        assert "前回の動画" in res2["end_screen_recommendation"]
        
        planner.add_video_to_series("series_1", "vid_3", "Vid 3")
        res3 = planner.optimize_playlist("series_1")
        assert res3["success"] is True
        assert "シリーズ第1回" in res3["end_screen_recommendation"]

def test_singleton():
    assert isinstance(series_planner, SeriesPlanner)

def test_register_series_invalid_inputs(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        # 空文字列のシリーズIDや特殊文字での動作を確認
        res1 = planner.register_series("", "Empty ID Title", "Theme")
        assert res1["title"] == "Empty ID Title"
        assert "" in planner.series_data["series"]

        res2 = planner.register_series("series_#@!", "Special ID Title", "Theme")
        assert res2["title"] == "Special ID Title"
        assert "series_#@!" in planner.series_data["series"]

def test_add_video_to_series_invalid_inputs(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        planner.register_series("series_1", "Title", "Theme")
        
        # 空文字列の動画IDやタイトルを追加
        assert planner.add_video_to_series("series_1", "", "Empty ID Title") is True
        # 追加されたことを確認
        assert planner.series_data["series"]["series_1"]["videos"][-1]["video_id"] == ""
        assert planner.series_data["series"]["series_1"]["videos"][-1]["title"] == "Empty ID Title"

def test_optimize_playlist_large_series(temp_registry_file):
    with patch("services.series_planner.SERIES_REGISTRY_FILE", temp_registry_file):
        planner = SeriesPlanner()
        planner.register_series("series_1", "Title", "Theme")
        
        # 動画を20本追加
        for i in range(1, 21):
            planner.add_video_to_series("series_1", f"vid_{i}", f"Video {i}")
            
        res = planner.optimize_playlist("series_1")
        assert res["success"] is True
        assert res["video_count"] == 20
        assert "シリーズ第1回" in res["end_screen_recommendation"]
        assert len(res["suggested_order"]) == 20
