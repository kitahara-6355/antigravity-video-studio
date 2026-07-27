"""
Tests for NHK subtitle quality scorer.
"""
import pytest
from backend.video_pipeline.nhk_subtitle_scorer import (
    NHKSubtitleScorer,
    SubtitleEntry,
)

class TestScoreNhkSubtitle:
    """NHK subtitle scorer test suite."""

    def test_full_compliance_grade_s(self):
        """TC1: All rules compliant segments -> grade 'S' (total_score >= 90)."""
        entries = [
            SubtitleEntry(index=1, start_time=0.0, end_time=2.0, text="こんにちは"),
            SubtitleEntry(index=2, start_time=3.0, end_time=5.0, text="テストです"),
            SubtitleEntry(index=3, start_time=6.0, end_time=8.0, text="字幕品質"),
            SubtitleEntry(index=4, start_time=9.0, end_time=11.0, text="検証中です"),
        ]
        scorer = NHKSubtitleScorer()
        report = scorer.score_text(entries)

        assert report.total_score >= 90
        assert report.grade == "S"  # 90点以上はSグレード
        assert "chars_per_line" in report.axis_scores
        assert "display_time" in report.axis_scores
        assert "audio_sync" in report.axis_scores

    def test_display_time_violation_detected(self):
        """TC2: Segment with short display time -> violation detected."""
        # 0.5s is below min_display_seconds (1.5s)
        entries = [
            SubtitleEntry(index=1, start_time=0.0, end_time=0.5, text="短い"),
            SubtitleEntry(index=2, start_time=2.0, end_time=4.0, text="普通です"),
        ]
        scorer = NHKSubtitleScorer()
        report = scorer.score_text(entries)

        time_violations = [p for p in report.problem_entries if p["axis"] == "display_time"]
        assert len(time_violations) >= 1
        assert time_violations[0]["entry_index"] == 1
        assert report.axis_scores["display_time"].score < report.axis_scores["display_time"].max_score

    def test_chars_per_line_too_long(self):
        """TC3: Line with too many chars -> chars_per_line score reduced."""
        # NHK基準は 1行あたり最大13文字。15文字あるので超過。
        entries = [
            SubtitleEntry(index=1, start_time=0.0, end_time=5.0, text="あいうえおかきくけこさしすせそ"),
        ]
        scorer = NHKSubtitleScorer()
        report = scorer.score_text(entries)

        char_violations = [p for p in report.problem_entries if p["axis"] == "chars_per_line"]
        assert len(char_violations) >= 1
        assert report.axis_scores["chars_per_line"].score < report.axis_scores["chars_per_line"].max_score

    def test_empty_segments_no_crash(self):
        """TC4: Empty segments -> no zero-division, returns valid report with 0 score."""
        entries = []
        scorer = NHKSubtitleScorer()
        report = scorer.score_text(entries)

        assert report.total_score == 0.0
        assert report.grade == "D"
        assert report.entry_count == 0
        assert len(report.suggestions) >= 1

    def test_analyze_line_break_quality_fallback(self, monkeypatch):
        """TC5: If fugashi fails with RuntimeError, fallback to regex analysis."""
        import backend.video_pipeline.nhk_subtitle_scorer as scorer_mod
        
        # モックして RuntimeError を発生させる
        def mock_fugashi_quality(text):
            raise RuntimeError("Mocked fugashi error")
            
        monkeypatch.setattr(scorer_mod, "_analyze_line_break_quality_fugashi", mock_fugashi_quality)
        monkeypatch.setattr(scorer_mod, "_HAS_FUGASHI", True)
        
        # 例外が発生せず、フォールバックの正規表現ベースの評価結果が返ることを確認
        # "こんにちは。\n世界" -> 句読点「。」の後の改行なので、正規表現ベースで 1.0 になるはず
        score = scorer_mod.analyze_line_break_quality("こんにちは。\n世界")
        assert score == 1.0
