# -*- coding: utf-8 -*-
import pytest
import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preview_system import (
    ScenePreview,
    PreviewReport,
    SubtitlePreviewGenerator,
    TelopPreviewGenerator,
    PreviewReportGenerator,
    create_preview_system
)

def test_capture_with_subtitle_success(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0)
        res = gen.capture_with_subtitle(video, srt, "00:01:00", "scene1_00-01-00")
        assert res is not None
        assert "scene1_00-01-00_sub.jpg" in str(res)

def test_capture_with_subtitle_failed(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="ffmpeg error")
        res = gen.capture_with_subtitle(video, srt, "00:01:00", "scene1_00-01-00")
        assert res is None

def test_capture_with_subtitle_exception(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Crash")):
        res = gen.capture_with_subtitle(video, srt, "00:01:00", "scene1_00-01-00")
        assert res is None

def test_capture_without_subtitle_success(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0)
        res = gen.capture_without_subtitle(video, "00:01:00", "scene1_00-01-00")
        assert res is not None
        assert "scene1_00-01-00.jpg" in str(res)

def test_capture_without_subtitle_failed(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        res = gen.capture_without_subtitle(video, "00:01:00", "scene1_00-01-00")
        assert res is None

def test_capture_without_subtitle_exception(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Crash")):
        res = gen.capture_without_subtitle(video, "00:01:00", "scene1_00-01-00")
        assert res is None

def test_generate_scene_previews_with_srt(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello", encoding="utf-8")
    
    with patch.object(gen, "capture_with_subtitle", return_value=tmp_path / "scene1_00-01-00_sub.jpg") as mock_cap:
        res = gen.generate_scene_previews("scene1", video, srt, ["00:01:00"])
        assert res.scene_name == "scene1"
        assert len(res.screenshots) == 1
        assert res.screenshots[0]["with_subtitle"] is True
        mock_cap.assert_called_once()

def test_generate_scene_previews_no_srt_or_missing(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "nonexistent.srt"
    
    with patch.object(gen, "capture_without_subtitle", return_value=tmp_path / "scene1_00-01-00.jpg") as mock_cap:
        res = gen.generate_scene_previews("scene1", video, srt, ["00:01:00"])
        assert res.scene_name == "scene1"
        assert len(res.screenshots) == 1
        assert res.screenshots[0]["with_subtitle"] is False
        mock_cap.assert_called_once()

def test_generate_telop_preview_success(tmp_path):
    gen = TelopPreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0)
        
        res = gen.generate_telop_preview(video, "00:01:00", "Telop Text", "scene1", "top")
        assert res is not None
        assert "scene1_telop.jpg" in str(res)
        
        res_bottom = gen.generate_telop_preview(video, "00:01:00", "Telop Text", "scene1", "bottom")
        assert res_bottom is not None

def test_generate_telop_preview_failed(tmp_path):
    gen = TelopPreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="drawtext error")
        res = gen.generate_telop_preview(video, "00:01:00", "Telop Text", "scene1", "top")
        assert res is None

def test_generate_telop_preview_exception(tmp_path):
    gen = TelopPreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Crash")):
        res = gen.generate_telop_preview(video, "00:01:00", "Telop Text", "scene1", "top")
        assert res is None

def test_report_generator_generate_and_save(tmp_path):
    gen = PreviewReportGenerator(tmp_path)
    
    scene = ScenePreview(
        scene_name="scene1",
        video_path="video.mp4",
        subtitle_path="subtitle.srt",
        screenshots=[
            {"timestamp": "00:01:00", "path": "sc1.jpg", "with_subtitle": True},
            {"timestamp": "00:02:00", "path": "sc2.jpg", "with_subtitle": False}
        ],
        telop_suggestions=[
            {"timestamp": "00:01:00", "text": "Telop Suggestion", "reason": "Intro"}
        ]
    )
    
    report = PreviewReport(
        title="Test Report",
        scenes=[scene],
        proper_noun_warnings=[
            {"found": "wrng", "correct": "correct", "location": "scene1"}
        ]
    )
    
    md_content = gen.generate(report)
    assert "Test Report" in md_content
    assert "carousel" in md_content
    assert "wrng" in md_content
    assert "Telop Suggestion" in md_content
    
    out_path = gen.save(report, "test_walkthrough.md")
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == md_content

def test_create_preview_system(tmp_path):
    system = create_preview_system(tmp_path)
    assert "subtitle_generator" in system
    assert "telop_generator" in system
    assert "report_generator" in system
    assert isinstance(system["subtitle_generator"], SubtitlePreviewGenerator)
    assert isinstance(system["telop_generator"], TelopPreviewGenerator)
    assert isinstance(system["report_generator"], PreviewReportGenerator)


def test_generate_scene_previews_multiple_timestamps_fallback(tmp_path):
    gen = SubtitlePreviewGenerator(tmp_path)
    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    
    timestamps = ["00:01:00", "00:02:00"]
    
    def mock_capture_with_subtitle(v, s, ts, out_name):
        if ts == "00:01:00":
            return tmp_path / f"{out_name}_sub.jpg"
        return None

    def mock_capture_without_subtitle(v, ts, out_name):
        return tmp_path / f"{out_name}.jpg"

    with patch.object(gen, "capture_with_subtitle", side_effect=mock_capture_with_subtitle) as mock_with,          patch.object(gen, "capture_without_subtitle", side_effect=mock_capture_without_subtitle) as mock_without,          patch("pathlib.Path.exists", return_value=True):
         
        res = gen.generate_scene_previews("scene1", video, srt, timestamps)
        
        assert res.scene_name == "scene1"
        assert len(res.screenshots) == 2
        
        assert res.screenshots[0]["timestamp"] == "00:01:00"
        assert res.screenshots[0]["with_subtitle"] is True
        
        assert res.screenshots[1]["timestamp"] == "00:02:00"
        assert res.screenshots[1]["with_subtitle"] is False
