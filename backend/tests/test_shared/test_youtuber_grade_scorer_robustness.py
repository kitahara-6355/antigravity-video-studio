import json
import pytest
from unittest.mock import patch, MagicMock
from backend.graded_previews.youtuber_grade_scorer import (
    get_video_info,
    get_loudness,
    score_against_youtuber_standard
)

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_height_zero(mock_get_loudness, mock_get_video_info):
    # height = 0 の場合、ZeroDivisionError が発生することを検証する
    mock_get_video_info.return_value = {
        "resolution": "1920x0",
        "width": 1920,
        "height": 0,
        "frame_rate": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "video_bitrate_kbps": 12000.0,
        "audio_bitrate_kbps": 192.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 600.0,
        "file_size_bytes": 90000000
    }
    mock_get_loudness.return_value = -14.0

    with pytest.raises(ZeroDivisionError):
        score_against_youtuber_standard(
            spec_path=None,
            video_path="dummy.mp4",
            segments=[],
            metadata={}
        )

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_extreme_aspect_ratio(mock_get_loudness, mock_get_video_info):
    # 極端なアスペクト比（例: 縦動画 1080x1920）の場合に aspect_points が 70点になることを検証
    mock_get_video_info.return_value = {
        "resolution": "1080x1920",
        "width": 1080,
        "height": 1920,
        "frame_rate": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "video_bitrate_kbps": 12000.0,
        "audio_bitrate_kbps": 192.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 600.0,
        "file_size_bytes": 90000000
    }
    mock_get_loudness.return_value = -14.0

    result = score_against_youtuber_standard(
        spec_path=None,
        video_path="dummy.mp4",
        segments=[],
        metadata={}
    )
    # aspect_points が 70 点であることを確認する (video_technical details の出力を確認)
    details = result["category_scores"]["video_technical"]["details"]
    aspect_detail = [d for d in details if "アスペクト比" in d][0]
    assert "70点" in aspect_detail
    assert "ACCEPTABLE" in aspect_detail

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_corrupted_json(mock_run, mock_exists):
    mock_exists.return_value = True
    # JSONパースエラーが発生した際、fallback_data が返されることを検証
    mock_run.return_value = MagicMock(stdout="{invalid_json}", stderr="", returncode=0)
    
    info = get_video_info("dummy.mp4")
    assert info["resolution"] == "1920x1080"
    assert info["width"] == 1920
    assert info["height"] == 1080

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_empty_metadata_keys(mock_get_loudness, mock_get_video_info):
    mock_get_video_info.return_value = {
        "resolution": "1920x1080",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "video_bitrate_kbps": 12000.0,
        "audio_bitrate_kbps": 192.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 600.0,
        "file_size_bytes": 90000000
    }
    mock_get_loudness.return_value = -14.0

    # metadata に必要なキーが無い、もしくは None が設定されている場合の頑健性検証
    result = score_against_youtuber_standard(
        spec_path=None,
        video_path="dummy.mp4",
        segments=[],
        metadata={
            "titles": None,
            "description": None,
            "tags": None
        }
    )
    assert result["total_score"] > 0
    assert result["category_scores"]["thumbnail_metadata"]["score"] > 0
