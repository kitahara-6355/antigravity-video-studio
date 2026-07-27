"""
soul_feedback → telop_render → compose の提案伝搬統合テスト
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from backend.video_pipeline.pipeline_coordinator import PipelineCoordinator
from backend.video_pipeline.soul_feedback_engine import (
    FeedbackOutput,
    Suggestion,
    _CONSTITUTION_PROHIBITED_PATTERNS,
)


@pytest.fixture
def temp_work_dir(tmp_path):
    return str(tmp_path)


def test_soul_feedback_stage_returns_suggestions(temp_work_dir):
    """soul_feedback ステージが suggestions と soul_score (0-100) を返すか検証。"""
    coordinator = PipelineCoordinator(work_dir=temp_work_dir)
    input_data = {
        "transcript_segments": [
            {"text": "こんにちは", "start": 0.0, "end": 1.0},
            {"text": "テスト動画です", "start": 1.0, "end": 2.5},
        ]
    }

    mock_suggestions = [
        Suggestion(
            category="テンポ",
            suggestion="カット間隔を短縮",
            evidence="過去高評価動画",
            priority="high",
            confidence=0.85,
        ),
        Suggestion(
            category="ビジュアル",
            suggestion="テロップ色を明るく",
            evidence="デザイン基準",
            priority="medium",
            confidence=0.75,
        ),
    ]
    mock_feedback = FeedbackOutput(
        suggestions=mock_suggestions,
        overall_score=85.0,
        analysis_summary="テンポとビジュアルの改善を提案",
    )

    with patch(
        "backend.video_pipeline.soul_feedback_engine.SoulFeedbackEngine.generate_suggestions",
        return_value=mock_feedback,
    ):
        result = coordinator.run_stage("soul_feedback", input_data)

    assert result.success is True
    output = result.output_data
    assert output.get("soul_feedback_done") is True
    assert "soul_suggestions" in output
    suggestions = output["soul_suggestions"]
    assert len(suggestions) == 2
    assert suggestions[0]["category"] == "テンポ"
    assert suggestions[0]["suggestion"] == "カット間隔を短縮"
    assert suggestions[0]["priority"] == "high"
    assert suggestions[0]["confidence"] == 0.85

    score = output.get("soul_score")
    assert score is not None
    assert 0.0 <= score <= 100.0
    assert output.get("soul_summary") == "テンポとビジュアルの改善を提案"


def test_telop_render_receives_soul_suggestions(temp_work_dir):
    """telop_render ステージが soul_suggestions を受領し透過返却するか検証。"""
    coordinator = PipelineCoordinator(work_dir=temp_work_dir)
    input_suggestions = [
        {"category": "テキスト", "suggestion": "フォントサイズ拡大", "priority": "high", "confidence": 0.9}
    ]
    input_data = {
        "job_dir": temp_work_dir,
        "transcript_segments": [{"text": "テスト字幕"}],
        "soul_suggestions": input_suggestions,
    }

    with patch("backend.video_pipeline.telop_renderer.TelopRenderer.render_batch") as mock_render:
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.image_path = "/path/to/image.png"
        mock_render.return_value = [mock_result]

        result = coordinator.run_stage("telop_render", input_data)

    assert result.success is True
    output = result.output_data
    assert "soul_suggestions" in output
    assert output["soul_suggestions"] == input_suggestions


def test_compose_receives_soul_suggestions(temp_work_dir):
    """compose ステージが soul_suggestions を受領し透過返却するか検証。"""
    coordinator = PipelineCoordinator(work_dir=temp_work_dir)
    input_suggestions = [
        {"category": "オーディオ", "suggestion": "BGM音量調整", "priority": "low", "confidence": 0.6}
    ]
    input_data = {
        "job_dir": temp_work_dir,
        "normalized_path": "/path/to/video.mp4",
        "subtitle_path": "/path/to/subs.srt",
        "soul_suggestions": input_suggestions,
    }

    with patch("backend.video_pipeline.video_composer.VideoComposer.compose") as mock_compose:
        mock_compose.return_value = MagicMock()

        result = coordinator.run_stage("compose", input_data)

    assert result.success is True
    output = result.output_data
    assert "soul_suggestions" in output
    assert output["soul_suggestions"] == input_suggestions


def test_soul_feedback_stage_fallback_on_error(temp_work_dir):
    """soul_feedback_engine でエラー発生時に安全にフォールバックするか検証。"""
    coordinator = PipelineCoordinator(work_dir=temp_work_dir)
    input_data = {
        "transcript_segments": [{"text": "エラー検証"}]
    }

    with patch(
        "backend.video_pipeline.soul_feedback_engine.SoulFeedbackEngine.generate_suggestions",
        side_effect=RuntimeError("エンジンエラー"),
    ):
        result = coordinator.run_stage("soul_feedback", input_data)

    assert result.success is True
    output = result.output_data
    assert output.get("soul_feedback_done") is True
    assert "soul_suggestions" not in output


def test_soul_suggestions_compliance_with_constitution(temp_work_dir):
    """生成された提案が PROJECT_CONSTITUTION.md の禁止パターンを含まないか検証。"""
    coordinator = PipelineCoordinator(work_dir=temp_work_dir)
    input_data = {
        "transcript_segments": [{"text": "憲法チェック"}]
    }

    mock_suggestions = [
        Suggestion(
            category="テンポ",
            suggestion="カット切り替えテンポの調整",
            evidence="OKパターン",
            priority="medium",
            confidence=0.8,
        )
    ]
    mock_feedback = FeedbackOutput(
        suggestions=mock_suggestions,
        overall_score=90.0,
        analysis_summary="憲法遵守チェック",
    )

    with patch(
        "backend.video_pipeline.soul_feedback_engine.SoulFeedbackEngine.generate_suggestions",
        return_value=mock_feedback,
    ):
        result = coordinator.run_stage("soul_feedback", input_data)

    assert result.success is True
    suggestions = result.output_data.get("soul_suggestions", [])
    for s in suggestions:
        text = f"{s['category']} {s['suggestion']}"
        for prohibited in _CONSTITUTION_PROHIBITED_PATTERNS:
            assert prohibited not in text, f"禁止キーワード '{prohibited}' が含まれています: {text}"
