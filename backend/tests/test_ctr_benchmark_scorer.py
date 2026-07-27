"""
Tests for ctr_benchmark_scorer.py — CTR benchmark auto-scoring module.

Test cases:
  1. Optimized metadata → grade "A"
  2. Title 60 chars → title_appeal deduction + improvement suggestion
  3. Tags 0 → metadata_optimization deduction
  4. template_id=None → DEFAULT_CTR_BENCHMARK used
  5. thumbnail_path=None → thumbnail_composition default 75
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from graded_previews.ctr_benchmark_scorer import (
    score_ctr_benchmark,
    TEMPLATE_CTR_BENCHMARKS,
    DEFAULT_CTR_BENCHMARK,
)


class TestCTRBenchmarkScorer:
    """CTR benchmark scorer test suite."""

    def test_optimized_metadata_grade_a(self):
        """TC-1: Fully optimized metadata should yield grade A."""
        metadata = {
            "titles": ["知らないと損する投資の3つの鉄則【2026年最新版・必見】"],  # ~30 chars, has number, power word, ?
            "description": (
                "この動画では投資初心者が知っておくべき鉄則を解説します。\n"
                "チャンネル登録: https://example.com/subscribe\n"
                "関連動画: https://example.com/related\n"
                "お問い合わせ: https://example.com/contact\n"
                "タイムスタンプ:\n"
                "0:00 はじめに"
            ),
            "tags": [
                "投資", "初心者", "2026", "資産運用", "株式",
                "NISA", "節約", "マネー", "副業", "金融",
                "お金", "貯金",
            ],
        }
        result = score_ctr_benchmark(
            metadata=metadata,
            template_id="mrbeast_entertainment",
            thumbnail_path="dummy_1280x720.jpg",
        )

        # Structure validation
        assert "predicted_ctr_percent" in result
        assert "benchmark_ctr_percent" in result
        assert "ctr_gap_percent" in result
        assert "total_score" in result
        assert "grade" in result
        assert "category_scores" in result
        assert "improvement_suggestions" in result

        # Category keys
        cats = result["category_scores"]
        assert "title_appeal" in cats
        assert "thumbnail_composition" in cats
        assert "metadata_optimization" in cats
        assert "genre_fit" in cats
        assert "competitive_benchmark" in cats

        # Category structure
        for cat_name, cat_data in cats.items():
            assert "score" in cat_data, f"{cat_name} missing 'score'"
            assert "weight" in cat_data, f"{cat_name} missing 'weight'"
            assert "details" in cat_data, f"{cat_name} missing 'details'"

        # Weights must sum to 1.0
        total_weight = sum(c["weight"] for c in cats.values())
        assert abs(total_weight - 1.0) < 0.01, f"Weights sum to {total_weight}, expected 1.0"

        # Grade A
        assert result["grade"] == "A", f"Expected grade A, got {result['grade']} (score={result['total_score']})"
        assert result["total_score"] >= 90

    def test_long_title_deduction(self):
        """TC-2: Title of 60 chars → title_appeal deduction and improvement suggestion."""
        long_title = "あ" * 60  # 60 characters
        metadata = {
            "titles": [long_title],
            "description": "説明文\n2行目\n3行目\nhttps://example.com",
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5",
                     "tag6", "tag7", "tag8", "tag9", "tag10"],
        }
        result = score_ctr_benchmark(metadata=metadata, template_id="hikakin_vlog")

        # Title score should be 50 (outside 15-45 range)
        title_score = result["category_scores"]["title_appeal"]["score"]
        assert title_score < 80, f"Expected title_appeal < 80 for 60-char title, got {title_score}"

        # Should have improvement suggestion about title
        suggestions = result["improvement_suggestions"]
        assert len(suggestions) > 0, "Expected improvement suggestions for long title"
        title_suggestions = [s for s in suggestions if "タイトル" in s or "文字" in s]
        assert len(title_suggestions) > 0, "Expected title-related improvement suggestion"

    def test_zero_tags_deduction(self):
        """TC-3: Tags=0 → metadata_optimization deduction."""
        metadata = {
            "titles": ["テスト動画タイトルです普通の長さ二十五文字以上三十五"],  # ~25 chars
            "description": "説明文1行目\n2行目\n3行目\nhttps://example.com",
            "tags": [],
        }
        result = score_ctr_benchmark(metadata=metadata, template_id="nhk_documentary")

        meta_score = result["category_scores"]["metadata_optimization"]["score"]
        assert meta_score < 80, f"Expected metadata_optimization < 80 for 0 tags, got {meta_score}"

    def test_no_template_uses_default_benchmark(self):
        """TC-4: template_id=None → DEFAULT_CTR_BENCHMARK (4.0) used."""
        metadata = {
            "titles": ["テスト動画のタイトル二十五文字以上三十五文字ギリギリ"],
            "description": "説明文\n2行目\n3行目\nhttps://example.com",
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5",
                     "tag6", "tag7", "tag8", "tag9", "tag10"],
        }
        result = score_ctr_benchmark(metadata=metadata, template_id=None)

        assert result["benchmark_ctr_percent"] == DEFAULT_CTR_BENCHMARK
        assert result["benchmark_ctr_percent"] == 4.0
        # Ensure no crash and valid output
        assert result["grade"] in ("A", "B", "C", "D", "F")

    def test_no_thumbnail_default_score(self):
        """TC-5: thumbnail_path=None → thumbnail_composition defaults to 75."""
        metadata = {
            "titles": ["テスト動画のタイトル二十五文字以上三十五文字ギリギリ"],
            "description": "説明文\n2行目\n3行目\nhttps://example.com",
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5",
                     "tag6", "tag7", "tag8", "tag9", "tag10"],
        }
        result = score_ctr_benchmark(metadata=metadata, thumbnail_path=None)

        thumb_score = result["category_scores"]["thumbnail_composition"]["score"]
        assert thumb_score == 75, f"Expected thumbnail_composition=75 when no thumbnail, got {thumb_score}"

    def test_title_length_and_question_bonus(self):
        """TC-6: Test _score_title_length and question mark bonus paths."""
        from graded_previews.ctr_benchmark_scorer import (
            _score_title_length,
            _calculate_title_bonuses,
        )

        # Test title length 20 (15 <= len <= 45 but not 25 <= len <= 35)
        score, suggestion = _score_title_length(20)
        assert score == 85
        assert suggestion is None

        # Test title length 10 (< 15)
        score, suggestion = _score_title_length(10)
        assert score == 50
        assert "短すぎます" in suggestion

        # Test question mark bonuses
        bonus, details = _calculate_title_bonuses("テストタイトル？")
        assert bonus == 5
        assert "疑問形ボーナス: +5" in details

        bonus, details = _calculate_title_bonuses("Test title?")
        assert bonus == 5
        assert "疑問形ボーナス: +5" in details

    def test_tag_count_variations(self):
        """TC-7: Test _score_tags with various tag counts."""
        from graded_previews.ctr_benchmark_scorer import _score_tags

        # Tag count 6 (5 <= count <= 7)
        score, detail, suggestion = _score_tags(["tag"] * 6)
        assert score == 80
        assert suggestion is None

        # Tag count 3 (1 <= count < 5)
        score, detail, suggestion = _score_tags(["tag"] * 3)
        assert score == 50
        assert "3個しかありません" in suggestion

        # Tag count 20 (count > 18)
        score, detail, suggestion = _score_tags(["tag"] * 20)
        assert score == 50
        assert "20個と多すぎます" in suggestion

    def test_description_variations(self):
        """TC-8: Test _score_description and metadata optimization integration."""
        from graded_previews.ctr_benchmark_scorer import _score_description

        # Description 2 lines, no link
        score, detail, suggestion = _score_description("Line 1\nLine 2")
        assert score == 80
        assert suggestion is None

        # Description 1 line, no link
        score, detail, suggestion = _score_description("Line 1")
        assert score == 50
        assert "説明文を3行以上にし" in suggestion

        # Ensure description suggestion propagates to final suggestions in score_ctr_benchmark
        metadata = {
            "titles": ["テスト動画のタイトル二十五文字以上三十五文字ギリギリ"],
            "description": "短すぎる説明文",
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5",
                     "tag6", "tag7", "tag8", "tag9", "tag10"],
        }
        result = score_ctr_benchmark(metadata=metadata)
        assert any("説明文を3行以上にし" in s for s in result["improvement_suggestions"])

    def test_genre_fit_score_boundaries(self):
        """TC-9: Test _get_genre_fit_score boundary for ratio >= 0.70."""
        from graded_previews.ctr_benchmark_scorer import _get_genre_fit_score

        # Test ratio 0.75 which should return score 70
        score = _get_genre_fit_score(0.75)
        assert score == 70

        # Test ratio 0.65 which should return score 50
        score = _get_genre_fit_score(0.65)
        assert score == 50
