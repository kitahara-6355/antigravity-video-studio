"""
test_quality_gate_integration.py — QualityGate 統合検証テスト
"""

from unittest.mock import patch, MagicMock
import pytest

from backend.video_pipeline.quality_gate import (
    QualityGate,
    QualityConfig,
    QualityReport,
    VisualScore,
    AudioScore,
    EncodingScore,
    SubtitleScore,
)


@pytest.fixture
def dummy_video_file(tmp_path):
    video = tmp_path / "test_video.mp4"
    video.write_bytes(b"dummy mp4 video content")
    return str(video)


def test_quality_gate_scoring_range_and_individual_scores(dummy_video_file):
    """(a, b) スコアが有効範囲内であり、各評価項目（視覚、音声、エンコード等）が個別スコアリングされることを検証"""
    gate = QualityGate()

    mock_visual = VisualScore(contrast_ratio=5.0, contrast_score=10.0, safe_area_compliance=100.0, safe_area_score=10.0, total=100.0)
    mock_audio = AudioScore(loudness_lufs=-14.0, total=100.0, available=True)
    mock_encoding = EncodingScore(crf_value=20.0, total=100.0, available=True)

    with patch.object(gate, "check_video_quality", return_value=mock_visual), \
         patch.object(gate, "check_audio_quality", return_value=mock_audio), \
         patch.object(gate, "_check_encoding_quality", return_value=mock_encoding):

        report = gate.evaluate(dummy_video_file)

        # 全体スコアが 0.0〜100.0 の範囲内であること
        assert 0.0 <= report.total_score <= 100.0

        # 個別スコアリング結果の確認
        assert report.visual_score is not None
        assert report.visual_score.total == 100.0
        assert report.audio_score is not None
        assert report.audio_score.total == 100.0
        assert report.encoding_score is not None
        assert report.encoding_score.total == 100.0


def test_quality_gate_threshold_pass(dummy_video_file):
    """(d) 閾値以上（デフォルト 80.0 点以上）の場合に PASS (passed=True) を返すことを検証"""
    config = QualityConfig(min_total_score=80.0)
    gate = QualityGate(config=config)

    mock_visual = VisualScore(total=90.0)
    mock_audio = AudioScore(total=85.0)
    mock_encoding = EncodingScore(total=95.0)

    with patch.object(gate, "check_video_quality", return_value=mock_visual), \
         patch.object(gate, "check_audio_quality", return_value=mock_audio), \
         patch.object(gate, "_check_encoding_quality", return_value=mock_encoding):

        report = gate.evaluate(dummy_video_file)

        assert report.total_score >= 80.0
        assert report.passed is True


def test_quality_gate_threshold_fail(dummy_video_file):
    """(c) 閾値未満（80.0 点未満）の場合に FAIL (passed=False) を返すことを検証"""
    config = QualityConfig(min_total_score=80.0)
    gate = QualityGate(config=config)

    mock_visual = VisualScore(total=30.0)
    mock_audio = AudioScore(total=20.0)
    mock_encoding = EncodingScore(total=40.0)

    with patch.object(gate, "check_video_quality", return_value=mock_visual), \
         patch.object(gate, "check_audio_quality", return_value=mock_audio), \
         patch.object(gate, "_check_encoding_quality", return_value=mock_encoding):

        report = gate.evaluate(dummy_video_file)

        assert report.total_score < 80.0
        assert report.passed is False


def test_check_subtitle_quality_delegation_to_nhk_scorer(tmp_path, dummy_video_file):
    """NHKSubtitleScorer が正常動作した場合にスコアと nhk_grade が正しくマッピングされることを検証"""
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nテスト字幕\n\n", encoding="utf-8")

    gate = QualityGate()
    mock_nhk_report = MagicMock()
    mock_nhk_report.total_score = 92.5
    mock_nhk_report.grade = "S"
    mock_nhk_report.axis_scores = {
        "chars_per_line": MagicMock(score=15.0),
        "display_time": MagicMock(score=15.0),
        "audio_sync": MagicMock(score=20.0),
        "line_break": MagicMock(score=12.5),
        "contrast": MagicMock(score=15.0),
        "safe_area": MagicMock(score=10.0),
        "font_consistency": MagicMock(score=5.0),
    }

    with patch("backend.video_pipeline.nhk_subtitle_scorer.NHKSubtitleScorer") as mock_scorer_cls:
        mock_instance = MagicMock()
        mock_instance.score.return_value = mock_nhk_report
        mock_scorer_cls.return_value = mock_instance

        score = gate.check_subtitle_quality(str(srt_file))

        assert score.total == 92.5
        assert score.chars_per_line == 15.0
        assert score.line_break_quality == 12.5
        assert gate._last_nhk_grade == "S"

        report = gate.evaluate(dummy_video_file, subtitle_path=str(srt_file))
        assert report.nhk_grade == "S"
        assert "nhk_grade" in report.to_dict()


def test_check_subtitle_quality_fallback_on_error(tmp_path):
    """NHKSubtitleScorer で例外が発生した際、従来の簡易評価にフォールバックされることを検証"""
    srt_file = tmp_path / "test_fallback.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:03,000\nフォールバック確認字幕\n\n", encoding="utf-8")

    gate = QualityGate()

    # quality_gate.py 内の遅延 import を ImportError で失敗させる
    import sys
    original = sys.modules.get("backend.video_pipeline.nhk_subtitle_scorer")
    sys.modules["backend.video_pipeline.nhk_subtitle_scorer"] = None  # type: ignore[assignment]
    try:
        score = gate.check_subtitle_quality(str(srt_file))
        assert score.total > 0
        assert gate._last_nhk_grade is None
    finally:
        if original is not None:
            sys.modules["backend.video_pipeline.nhk_subtitle_scorer"] = original
        else:
            sys.modules.pop("backend.video_pipeline.nhk_subtitle_scorer", None)


