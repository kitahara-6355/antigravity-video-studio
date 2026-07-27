"""
test_refine_quality.py — refine 適用前後のセグメント品質比較ユニットテスト

文字起こし後のタイムスタンプ精密化 (refine_timestamps) 処理に関して、
セグメント数保持、タイムスタンプ変動範囲、テキスト不変性、無効化時の挙動、
空データ安全性をモックを用いて検証する。
"""

import pytest
from unittest.mock import patch, MagicMock
from video_pipeline.transcription_service import TranscriptionService, TranscriptSegment
from video_pipeline.stable_ts_wrapper import StableTsWrapper


def test_refine_quality_segment_count_and_content_preservation():
    """refine 適用前後でセグメント数(N->N)およびテキスト内容が保持され、タイムスタンプが±0.5秒以内であることを検証"""
    service = TranscriptionService(model_name="base", language="ja", refine_enabled=True)
    
    orig_segments = [
        TranscriptSegment(start=1.0, end=3.0, text="第一文です。", confidence=0.9),
        TranscriptSegment(start=3.5, end=6.0, text="第二文です。", confidence=0.85),
        TranscriptSegment(start=6.2, end=9.0, text="第三文です。", confidence=0.88),
    ]

    # ±0.5秒以内の微調整されたタイムスタンプを模したモック結果
    refined_segments = [
        TranscriptSegment(start=1.2, end=2.9, text="第一文です。", confidence=0.9),
        TranscriptSegment(start=3.4, end=6.1, text="第二文です。", confidence=0.85),
        TranscriptSegment(start=6.0, end=8.9, text="第三文です。", confidence=0.88),
    ]

    mock_wrapper = MagicMock()
    mock_wrapper.refine_timestamps.return_value = refined_segments

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=True), \
         patch.object(service, "_transcribe_with_stable_ts", return_value=orig_segments), \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper", return_value=mock_wrapper):

        result = service.transcribe("dummy.wav")

        assert result.success is True
        assert result.model_used == "stable-ts/base+refined"
        # a. セグメント数が保持されること (3件 -> 3件)
        assert len(result.segments) == len(orig_segments)

        for orig, ref in zip(orig_segments, result.segments):
            # b. 各タイムスタンプが元の±0.5秒以内であること
            assert abs(ref.start - orig.start) <= 0.5
            assert abs(ref.end - orig.end) <= 0.5
            # c. テキスト内容が変化しないこと
            assert ref.text == orig.text


def test_refine_disabled_does_not_call_refine():
    """d. refine_enabled=False 時、refine_timestamps が呼ばれないこと"""
    service = TranscriptionService(model_name="base", language="ja", refine_enabled=False)
    orig_segments = [
        TranscriptSegment(start=0.0, end=2.0, text="テストテキスト", confidence=0.9)
    ]

    mock_wrapper = MagicMock()

    with patch("os.path.exists", return_value=True), \
         patch.object(service, "_is_stable_ts_available", return_value=True), \
         patch.object(service, "_transcribe_with_stable_ts", return_value=orig_segments), \
         patch("backend.video_pipeline.stable_ts_wrapper.StableTsWrapper", return_value=mock_wrapper):

        result = service.transcribe("dummy.wav")

        assert result.success is True
        assert result.model_used == "stable-ts/base"
        mock_wrapper.refine_timestamps.assert_not_called()
        assert result.segments[0].start == 0.0


def test_refine_empty_segments_handling():
    """e. 空セグメントリストに対して refine が安全に動作すること"""
    wrapper = StableTsWrapper(model_name="base", language="ja")
    
    # segments が空リストの場合、空リストがそのまま安全に返されること
    refined = wrapper.refine_timestamps("dummy.wav", [])
    assert refined == []
