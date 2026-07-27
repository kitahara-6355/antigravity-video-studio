"""Tests for youtuber_grade_scorer public interface wrappers.

Task 2 で追加した NHKQualityScorer 委譲用インターフェースのテスト:
- measure_loudness()
- evaluate_subtitle_quality()
- measure_cut_frequency()
"""
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# measure_loudness
# ---------------------------------------------------------------------------

class TestMeasureLoudness:
    """measure_loudness() のテスト"""

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-14.0)
    def test_returns_dict_with_required_keys(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert isinstance(result, dict)
        assert "lufs" in result
        assert "target" in result
        assert "in_range" in result

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-14.0)
    def test_in_range_true(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert result["lufs"] == -14.0
        assert result["in_range"] is True

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-20.0)
    def test_in_range_false_too_low(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert result["in_range"] is False

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-10.0)
    def test_in_range_false_too_high(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert result["in_range"] is False

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-16.0)
    def test_boundary_low(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert result["in_range"] is True

    @patch("graded_previews.youtuber_grade_scorer.get_loudness", return_value=-13.0)
    def test_boundary_high(self, mock_gl):
        from graded_previews.youtuber_grade_scorer import measure_loudness
        result = measure_loudness("dummy.mp4")
        assert result["in_range"] is True


# ---------------------------------------------------------------------------
# evaluate_subtitle_quality
# ---------------------------------------------------------------------------

class TestEvaluateSubtitleQuality:
    """evaluate_subtitle_quality() のテスト"""

    def test_empty_segments(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        result = evaluate_subtitle_quality([])
        assert result["avg_speed_cps"] == 0.0
        assert result["max_chars_per_line"] == 0
        assert result["score"] == 100  # 0.0 cps → excellent, 0 chars → excellent

    def test_excellent_quality(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        segments = [
            {"start": 0.0, "end": 3.0, "text": "こんにちは"},      # 5/3 ≈ 1.67 cps
            {"start": 3.0, "end": 6.0, "text": "テスト文章"},      # 5/3 ≈ 1.67 cps
        ]
        result = evaluate_subtitle_quality(segments)
        assert result["speed_grade"] == "excellent"
        assert result["line_grade"] == "excellent"  # 5 chars < 15
        assert result["score"] == 100

    def test_long_line_lowers_grade(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        segments = [
            {"start": 0.0, "end": 10.0, "text": "これは非常に長い行で15文字を超えています確認テスト"},
        ]
        result = evaluate_subtitle_quality(segments)
        assert result["max_chars_per_line"] > 15
        assert result["line_grade"] != "excellent"

    def test_fast_speed_lowers_grade(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        segments = [
            {"start": 0.0, "end": 1.0, "text": "これは高速表示のテストです十文字超"},  # >10 cps
        ]
        result = evaluate_subtitle_quality(segments)
        assert result["speed_grade"] == "fail"

    def test_non_list_input(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        result = evaluate_subtitle_quality("not a list")
        assert isinstance(result, dict)
        assert result["avg_speed_cps"] == 0.0

    def test_non_dict_segments_skipped(self):
        from graded_previews.youtuber_grade_scorer import evaluate_subtitle_quality
        result = evaluate_subtitle_quality(["bad", 123, None])
        assert result["avg_speed_cps"] == 0.0


# ---------------------------------------------------------------------------
# measure_cut_frequency
# ---------------------------------------------------------------------------

class TestMeasureCutFrequency:
    """measure_cut_frequency() のテスト"""

    def test_returns_dict_with_required_keys(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        result = measure_cut_frequency([], 60.0)
        assert "cuts_per_min" in result
        assert "segment_count" in result
        assert "grade" in result
        assert "score" in result
        assert "max_gap_sec" in result

    def test_excellent_cut_frequency(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        # 10 segments in 60 sec = 10 cuts/min → excellent
        segments = [{"start": i * 6.0, "end": (i + 1) * 6.0 - 0.5, "text": f"seg{i}"} for i in range(10)]
        result = measure_cut_frequency(segments, 60.0)
        assert result["grade"] == "excellent"
        assert result["score"] == 100
        assert result["segment_count"] == 10

    def test_low_cut_frequency(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        # 2 segments in 60 sec = 2 cuts/min → fail
        segments = [
            {"start": 0.0, "end": 30.0, "text": "a"},
            {"start": 30.0, "end": 60.0, "text": "b"},
        ]
        result = measure_cut_frequency(segments, 60.0)
        assert result["grade"] == "fail"
        assert result["score"] == 40

    def test_max_gap_calculation(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        segments = [
            {"start": 0.0, "end": 5.0, "text": "a"},
            {"start": 10.0, "end": 15.0, "text": "b"},  # gap = 5.0
            {"start": 16.0, "end": 20.0, "text": "c"},  # gap = 1.0
        ]
        result = measure_cut_frequency(segments, 60.0)
        assert result["max_gap_sec"] == 5.0

    def test_empty_segments(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        result = measure_cut_frequency([], 60.0)
        assert result["segment_count"] == 0
        assert result["cuts_per_min"] == 0.0
        assert result["max_gap_sec"] == 0.0

    def test_non_list_input(self):
        from graded_previews.youtuber_grade_scorer import measure_cut_frequency
        result = measure_cut_frequency("bad", 60.0)
        assert result["segment_count"] == 0
