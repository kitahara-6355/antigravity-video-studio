"""
test_stable_ts_wrapper.py — StableTsWrapper 単体テスト
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from backend.video_pipeline.stable_ts_wrapper import StableTsWrapper
from backend.video_pipeline.transcription_service import TranscriptSegment


@pytest.fixture
def dummy_audio_file(tmp_path):
    audio_file = tmp_path / "test_audio.wav"
    audio_file.write_bytes(b"dummy audio content")
    return str(audio_file)


def test_is_available():
    with patch("builtins.__import__", side_effect=ImportError("No module named 'stable_whisper'")):
        assert StableTsWrapper.is_available() is False

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True):
        assert StableTsWrapper.is_available() is True


def test_transcribe_success(dummy_audio_file):
    mock_seg1 = MagicMock(spec=["start", "end", "text", "avg_logprob"])
    mock_seg1.start = 0.0
    mock_seg1.end = 2.5
    mock_seg1.text = " Hello World "
    mock_seg1.avg_logprob = -0.15

    mock_result = MagicMock()
    mock_result.segments = [mock_seg1]

    mock_model = MagicMock()
    mock_model.transcribe.return_value = mock_result

    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    wrapper = StableTsWrapper(model_name="base", language="ja")

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):
        segments = wrapper.transcribe(dummy_audio_file)

    assert len(segments) == 1
    assert isinstance(segments[0], TranscriptSegment)
    assert segments[0].start == 0.0
    assert segments[0].end == 2.5
    assert segments[0].text == "Hello World"
    assert segments[0].confidence == -0.15
    mock_stable_whisper.load_model.assert_called_once_with("base")
    mock_model.transcribe.assert_called_once_with(dummy_audio_file, language="ja")


def test_transcribe_model_load_failure(dummy_audio_file):
    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.side_effect = RuntimeError("Failed to load model")

    wrapper = StableTsWrapper()

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):
        segments = wrapper.transcribe(dummy_audio_file)

    assert segments == []


def test_transcribe_empty_segments(dummy_audio_file):
    mock_result = MagicMock()
    mock_result.segments = []

    mock_model = MagicMock()
    mock_model.transcribe.return_value = mock_result

    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    wrapper = StableTsWrapper()

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):
        segments = wrapper.transcribe(dummy_audio_file)

    assert segments == []


def test_refine_timestamps_success(dummy_audio_file):
    input_segments = [
        TranscriptSegment(start=0.0, end=3.0, text="テスト字幕", confidence=0.9)
    ]

    mock_refined_seg = MagicMock()
    mock_refined_seg.start = 0.1
    mock_refined_seg.end = 2.9
    mock_refined_seg.text = "テスト字幕"

    mock_refined_result = MagicMock()
    mock_refined_result.segments = [mock_refined_seg]

    mock_model = MagicMock()
    mock_model.refine.return_value = mock_refined_result

    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    wrapper = StableTsWrapper()

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):
        refined = wrapper.refine_timestamps(dummy_audio_file, input_segments)

    assert len(refined) == 1
    assert refined[0].start == 0.1
    assert refined[0].end == 2.9
    assert refined[0].text == "テスト字幕"
    assert refined[0].confidence == 0.9


def test_refine_timestamps_empty_list(dummy_audio_file):
    wrapper = StableTsWrapper()
    refined = wrapper.refine_timestamps(dummy_audio_file, [])
    assert refined == []
