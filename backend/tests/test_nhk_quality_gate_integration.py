"""
test_nhk_quality_gate_integration.py — NHK字幕品質スコア統合検証テスト
"""

from unittest.mock import patch, MagicMock
import pytest

from backend.video_pipeline.quality_gate import QualityGate, SubtitleScore, QualityReport


@pytest.fixture
def dummy_video_file(tmp_path):
    video = tmp_path / "test_video.mp4"
    video.write_bytes(b"dummy video content")
    return str(video)


@pytest.fixture
def dummy_srt_file(tmp_path):
    srt = tmp_path / "test_sub.srt"
    srt_content = (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "テスト字幕です\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:08,000\n"
        "二番目の字幕\n\n"
    )
    srt.write_text(srt_content, encoding="utf-8")
    return str(srt)


def test_evaluate_with_srt_and_video(dummy_video_file, dummy_srt_file):
    """(a) SRTファイル + 動画ファイルのダミーで evaluate() を実行しスコアおよび nhk_grade が正常であることを検証"""
    gate = QualityGate()
    report = gate.evaluate(dummy_video_file, subtitle_path=dummy_srt_file)

    assert report.subtitle_score is not None
    assert 0.0 <= report.subtitle_score.total <= 100.0
    assert report.nhk_grade in ("S", "A", "B", "C", "D")


def test_evaluate_without_srt(dummy_video_file):
    """(b) SRTファイルなしで evaluate() を実行し subtitle_score および nhk_grade が None であることを検証"""
    gate = QualityGate()
    report = gate.evaluate(dummy_video_file, subtitle_path=None)

    assert report.subtitle_score is None
    assert report.nhk_grade is None


def test_evaluate_nhk_scorer_import_error_simulation(dummy_video_file, dummy_srt_file):
    """(c) NHKSubtitleScorer のインポート失敗をシミュレートしフォールバック評価が動作することを検証"""
    gate = QualityGate()
    with patch("backend.video_pipeline.nhk_subtitle_scorer.NHKSubtitleScorer", side_effect=ImportError("Failed import")):
        report = gate.evaluate(dummy_video_file, subtitle_path=dummy_srt_file)

        assert report.subtitle_score is not None
        assert 0.0 <= report.subtitle_score.total <= 100.0
        assert report.nhk_grade is None


def test_evaluate_7axis_mapping_with_mock(dummy_video_file, dummy_srt_file):
    """(d) 7軸スコアの個別値が SubtitleScore のフィールドに正しく反映されることを検証"""
    gate = QualityGate()

    mock_report = MagicMock()
    mock_report.total_score = 88.0
    mock_report.grade = "A"
    mock_report.axis_scores = {
        "chars_per_line": MagicMock(score=14.0),
        "display_time": MagicMock(score=13.0),
        "audio_sync": MagicMock(score=18.0),
        "line_break": MagicMock(score=12.0),
        "contrast": MagicMock(score=14.0),
        "safe_area": MagicMock(score=9.0),
        "font_consistency": MagicMock(score=8.0),
    }

    with patch("backend.video_pipeline.nhk_subtitle_scorer.NHKSubtitleScorer") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.score.return_value = mock_report
        mock_cls.return_value = mock_instance

        report = gate.evaluate(dummy_video_file, subtitle_path=dummy_srt_file)

        sub = report.subtitle_score
        assert sub is not None
        assert sub.total == 88.0
        assert sub.chars_per_line == 14.0
        assert sub.display_duration_avg == 13.0
        assert sub.sync_offset_ms == 18.0
        assert sub.line_break_quality == 12.0
        assert sub.contrast_ratio == 14.0
        assert sub.safe_area_compliance == 9.0
        assert sub.font_consistency == 8.0
        assert report.nhk_grade == "A"
