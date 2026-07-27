"""
test_stable_ts_accuracy.py — stable-ts refine 機能の精度と堅牢性検証テスト

モックを使用したユニットテストとして設計され、実際にWhisperモデルをダウンロードすることなく
refine_timestamps メソッドの挙動を検証します。
"""

from unittest.mock import MagicMock, patch
import pytest

from backend.video_pipeline.stable_ts_wrapper import StableTsWrapper
from backend.video_pipeline.transcription_service import TranscriptSegment


@pytest.fixture
def dummy_audio_file(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"dummy audio binary data")
    return str(audio)


def test_refine_timestamps_precision(dummy_audio_file):
    """(a, c) refine_timestamps が元のタイムスタンプを精密化し、±0.5秒以内に収まることを検証"""
    wrapper = StableTsWrapper(model_name="base", language="ja")

    original_segments = [
        TranscriptSegment(start=1.0, end=4.0, text="テスト字幕1", confidence=0.85),
        TranscriptSegment(start=4.5, end=8.0, text="テスト字幕2", confidence=0.90),
    ]

    # モックの作成: 1.0 -> 1.2, 4.0 -> 3.9 (差分: +0.2, -0.1)
    mock_seg1 = MagicMock()
    mock_seg1.start = 1.2
    mock_seg1.end = 3.9
    mock_seg1.text = "テスト字幕1"

    # モックの作成: 4.5 -> 4.3, 8.0 -> 8.1 (差分: -0.2, +0.1)
    mock_seg2 = MagicMock()
    mock_seg2.start = 4.3
    mock_seg2.end = 8.1
    mock_seg2.text = "テスト字幕2"

    mock_result = MagicMock()
    mock_result.segments = [mock_seg1, mock_seg2]

    mock_model = MagicMock()
    mock_model.refine.return_value = mock_result

    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):

        refined_segments = wrapper.refine_timestamps(dummy_audio_file, original_segments)

    # 精度と範囲の検証
    assert len(refined_segments) == len(original_segments)
    for orig, ref in zip(original_segments, refined_segments):
        assert abs(ref.start - orig.start) <= 0.5
        assert abs(ref.end - orig.end) <= 0.5
        assert ref.text == orig.text


def test_refine_timestamps_count_consistency(dummy_audio_file):
    """(b) 入力セグメント数と出力セグメント数が一致することを検証"""
    wrapper = StableTsWrapper()

    original_segments = [
        TranscriptSegment(start=0.0, end=2.0, text="Seg1"),
        TranscriptSegment(start=2.0, end=4.0, text="Seg2"),
        TranscriptSegment(start=4.0, end=6.0, text="Seg3"),
    ]

    mock_segs = []
    for s in original_segments:
        m = MagicMock()
        m.start = s.start + 0.05
        m.end = s.end - 0.05
        m.text = s.text
        mock_segs.append(m)

    mock_result = MagicMock()
    mock_result.segments = mock_segs
    mock_model = MagicMock()
    mock_model.refine.return_value = mock_result
    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):

        refined = wrapper.refine_timestamps(dummy_audio_file, original_segments)

    assert len(refined) == 3


def test_refine_timestamps_empty_input(dummy_audio_file):
    """(d) 空セグメントリストの場合に空リストを返すことを検証"""
    wrapper = StableTsWrapper()
    assert wrapper.refine_timestamps(dummy_audio_file, []) == []


def test_refine_timestamps_fallback_on_error(dummy_audio_file):
    """(e) refine 処理中にエラーが発生した場合にオリジナルセグメントをそのまま返すことを検証"""
    wrapper = StableTsWrapper()

    original_segments = [
        TranscriptSegment(start=0.0, end=5.0, text="フォールバック確認用", confidence=0.8)
    ]

    mock_model = MagicMock()
    mock_model.refine.side_effect = RuntimeError("refine failed inside C++ extension")
    mock_stable_whisper = MagicMock()
    mock_stable_whisper.load_model.return_value = mock_model

    with patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper.is_available", return_value=True), \
         patch.dict("sys.modules", {"stable_whisper": mock_stable_whisper}):

        refined = wrapper.refine_timestamps(dummy_audio_file, original_segments)

    # 元のリストがそのまま返されること
    assert refined == original_segments
