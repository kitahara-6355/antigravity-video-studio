import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import json
import logging
from unittest.mock import MagicMock, patch, mock_open, AsyncMock
import pytest

from self_review_engine import (
    QualityScore,
    ReviewResult,
    ImprovementRecord,
    SelfReviewEngine,
    advisor_then_review,
    review_generation,
    review_and_improve,
    self_review_engine
)

# ロギング設定
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_gemini_client():
    with patch("self_review_engine.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_get_model():
    with patch("self_review_engine.get_model") as mock_model:
        mock_model.return_value = "mocked-model"
        yield mock_model


def test_data_classes():
    """データクラスの初期化と構造検証"""
    score = QualityScore(
        context_fit=0.9,
        constitution_fit=0.8,
        technical_quality=0.7,
        overall=0.8,
        details={"info": "test"}
    )
    assert score.context_fit == 0.9
    assert score.overall == 0.8
    assert score.details == {"info": "test"}

    result = ReviewResult(
        passed=True,
        score=score,
        issues=["issue1"],
        suggestions=["suggestion1"],
        improvement_applied=True,
        improvement_history=[{"round": 1}]
    )
    assert result.passed is True
    assert result.issues == ["issue1"]
    assert result.improvement_applied is True

    record = ImprovementRecord(
        round=1,
        original_score=0.5,
        improved_score=0.8,
        changes_made=["fixed stuff"]
    )
    assert record.round == 1
    assert record.original_score == 0.5
    assert record.improved_score == 0.8
    assert isinstance(record.timestamp, str)


def test_load_constitution_exists():
    """憲法ファイルが存在する場合の読み込み"""
    dummy_const = {"principles": ["Honesty", "Quality"]}
    
    with patch("self_review_engine.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=json.dumps(dummy_const))):
        engine = SelfReviewEngine()
        assert engine.constitution == dummy_const


def test_load_constitution_not_exists():
    """憲法ファイルが存在しない場合の読み込み（空辞書）"""
    with patch("self_review_engine.Path.exists", return_value=False):
        engine = SelfReviewEngine()
        assert engine.constitution == {}


def test_review_success_passed(mock_gemini_client, mock_get_model):
    """レビュー成功（閾値以上でpassed）"""
    mock_response = MagicMock()
    mock_response.text = """
    ```json
    {
      "context_fit": 0.85,
      "constitution_fit": 0.90,
      "technical_quality": 0.80,
      "issues": [],
      "suggestions": []
    }
    ```
    """
    mock_gemini_client.models.generate_content.return_value = mock_response

    engine = SelfReviewEngine()
    result = engine.review(
        content="Test content",
        generation_type="telop",
        context={"topic": "test"}
    )

    assert result.passed is True
    assert result.score.context_fit == 0.85
    assert result.score.overall == pytest.approx(0.85)
    assert len(result.issues) == 0


def test_review_success_failed(mock_gemini_client, mock_get_model):
    """レビュー成功（閾値未満でfailed）"""
    mock_response = MagicMock()
    mock_response.text = """
    {
      "context_fit": 0.50,
      "constitution_fit": 0.50,
      "technical_quality": 0.50,
      "issues": ["too short"],
      "suggestions": ["make it longer"]
    }
    """
    mock_gemini_client.models.generate_content.return_value = mock_response

    engine = SelfReviewEngine()
    result = engine.review(
        content="Short text",
        generation_type="telop",
        context={}
    )

    assert result.passed is False
    assert result.score.context_fit == 0.50
    assert result.issues == ["too short"]
    assert result.suggestions == ["make it longer"]


def test_review_exception(mock_gemini_client, mock_get_model):
    """レビュー中のAPI例外（フォールバックが機能すること）"""
    mock_gemini_client.models.generate_content.side_effect = Exception("API Error")

    engine = SelfReviewEngine()
    result = engine.review("content", "telop", {})

    assert result.passed is True
    assert result.score.overall == 0.75
    assert len(result.issues) == 0


def test_parse_review_invalid_json():
    """パースエラー（JSONが切り出せない、またはJSONDecodeError時）のフォールバック"""
    engine = SelfReviewEngine()
    
    result1 = engine._parse_review("no json here")
    assert result1.passed is True
    assert result1.score.overall == 0.75
    
    result2 = engine._parse_review("{ 'context_fit': invalid }")
    assert result2.passed is True
    assert result2.score.overall == 0.75


def test_parse_review_missing_keys(mock_gemini_client, mock_get_model):
    """JSONにキーが欠落している場合（デフォルト値0.5が使われること）"""
    engine = SelfReviewEngine()
    result = engine._parse_review("{}")
    assert result.passed is False
    assert result.score.context_fit == 0.5
    assert result.score.constitution_fit == 0.5
    assert result.score.technical_quality == 0.5
    assert result.score.overall == 0.5


def test_review_and_improve_immediate_pass(mock_gemini_client, mock_get_model):
    """改善不要（最初から合格）の場合"""
    mock_response = MagicMock()
    mock_response.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9}'
    mock_gemini_client.models.generate_content.return_value = mock_response

    engine = SelfReviewEngine()
    content, result = engine.review_and_improve("Nice text", "telop", {})

    assert content == "Nice text"
    assert result.passed is True
    assert result.improvement_applied is False
    assert len(result.improvement_history) == 0


def test_review_and_improve_with_custom_func(mock_gemini_client, mock_get_model):
    """カスタム改善関数を使用して合格する場合"""
    mock_response_fail = MagicMock()
    mock_response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    
    mock_response_pass = MagicMock()
    mock_response_pass.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9}'
    
    mock_gemini_client.models.generate_content.side_effect = [mock_response_fail, mock_response_pass]

    engine = SelfReviewEngine()
    
    def mock_improve(content, issues, suggestions):
        return "Improved " + content

    content, result = engine.review_and_improve("original", "telop", {}, improve_func=mock_improve)

    assert content == "Improved original"
    assert result.passed is True
    assert result.improvement_applied is True
    assert len(result.improvement_history) == 1
    assert result.improvement_history[0]["round"] == 1
    assert result.improvement_history[0]["issues"] == ["bad"]


def test_review_and_improve_max_rounds(mock_gemini_client, mock_get_model):
    """最大改善ラウンド（3回）に達しても不合格の場合"""
    mock_response_fail = MagicMock()
    mock_response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    
    mock_improve_resp = MagicMock()
    mock_improve_resp.text = "Newly improved content"
    
    mock_gemini_client.models.generate_content.side_effect = [
        mock_response_fail,  # review 1
        mock_improve_resp,   # default_improve 1
        mock_response_fail,  # review 2
        mock_improve_resp,   # default_improve 2
        mock_response_fail,  # review 3
        mock_improve_resp,   # default_improve 3
        mock_response_fail,  # review final
    ]

    engine = SelfReviewEngine()
    content, result = engine.review_and_improve("original", "telop", {})

    assert content == "Newly improved content"
    assert result.passed is False
    assert result.improvement_applied is True
    assert len(result.improvement_history) == 3


def test_default_improve_exception(mock_gemini_client, mock_get_model):
    """デフォルト改善処理でAPI例外が発生した場合（元のコンテンツを返す）"""
    mock_gemini_client.models.generate_content.side_effect = Exception("API Error")
    
    engine = SelfReviewEngine()
    result = ReviewResult(
        passed=False,
        score=QualityScore(0.5, 0.5, 0.5, 0.5),
        issues=["issue"],
        suggestions=["suggest"]
    )
    
    improved = engine._default_improve("original", result, {})
    assert improved == "original"


@pytest.fixture
def mock_advisor_gate():
    mock_advisor = MagicMock()
    mock_advisor_module = MagicMock()
    mock_advisor_module.advisor_gate = mock_advisor
    
    with patch.dict("sys.modules", {
        "agents": mock_advisor_module,
        "agents.advisor_gate": mock_advisor_module
    }):
        yield mock_advisor


@pytest.mark.asyncio
async def test_advisor_then_review_rejected(mock_advisor_gate):
    """AdvisorGate が pre-check で rejected と判定した場合"""
    mock_verdict = MagicMock()
    mock_verdict.verdict = "rejected"
    mock_verdict.reasoning = "Not safe"
    mock_verdict.corrections = [{"suggested": "do this"}]

    mock_advisor_gate.should_review.return_value = True
    # AsyncMock を使用して await 可能にする
    mock_advisor_gate.review_before_execution = AsyncMock(return_value=mock_verdict)

    with patch.object(self_review_engine, "review_and_improve") as mock_improve_func:
        content, result = await advisor_then_review(
            content="content",
            gen_type="telop",
            context={},
            task_description="task",
            definition_of_done="dod"
        )
        
        assert result.passed is False
        assert "AdvisorGate rejected: Not safe" in result.issues[0]
        assert result.suggestions == ["do this"]
        mock_improve_func.assert_not_called()


@pytest.mark.asyncio
async def test_advisor_then_review_accepted(mock_advisor_gate):
    """AdvisorGate が accepted と判定した場合、通常レビューへ進行すること"""
    mock_verdict = MagicMock()
    mock_verdict.verdict = "accepted"

    mock_advisor_gate.should_review.return_value = True
    # AsyncMock を使用して await 可能にする
    mock_advisor_gate.review_before_execution = AsyncMock(return_value=mock_verdict)

    with patch.object(self_review_engine, "review_and_improve") as mock_improve_func:
        mock_improve_func.return_value = ("improved_content", "mock_result")
        content, result = await advisor_then_review(
            content="content",
            gen_type="telop",
            context={}
        )
        
        assert content == "improved_content"
        assert result == "mock_result"
        mock_improve_func.assert_called_once()


@pytest.mark.asyncio
async def test_advisor_then_review_import_error():
    """AdvisorGate インポートエラー時、通常レビューへ進行すること"""
    orig_import = __import__
    def import_mock(name, *args, **kwargs):
        if "advisor_gate" in name:
            raise ImportError("mock import error")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=import_mock):
        with patch.object(self_review_engine, "review_and_improve") as mock_improve_func:
            mock_improve_func.return_value = ("improved_content", "mock_result")
            content, result = await advisor_then_review(
                content="content",
                gen_type="telop",
                context={}
            )
            assert content == "improved_content"
            assert result == "mock_result"
            mock_improve_func.assert_called_once()


@pytest.mark.asyncio
async def test_advisor_then_review_general_exception(mock_advisor_gate):
    """AdvisorGate で一般的な例外が発生した場合、通常レビューへ進行すること"""
    mock_advisor_gate.should_review.side_effect = Exception("General error")

    with patch.object(self_review_engine, "review_and_improve") as mock_improve_func:
        mock_improve_func.return_value = ("improved_content", "mock_result")
        content, result = await advisor_then_review(
            content="content",
            gen_type="telop",
            context={}
        )
        assert content == "improved_content"
        assert result == "mock_result"
        mock_improve_func.assert_called_once()


def test_wrapper_functions(mock_gemini_client, mock_get_model):
    """簡易ラッパー関数 (review_generation, review_and_improve) の動作確認"""
    mock_response = MagicMock()
    mock_response.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9}'
    mock_gemini_client.models.generate_content.return_value = mock_response

    orig_client = self_review_engine.client
    orig_model = self_review_engine.model
    try:
        self_review_engine.client = mock_gemini_client
        self_review_engine.model = "mocked-model"

        result = review_generation("test", "telop", {})
        assert result.passed is True

        content, result = review_and_improve("test", "telop", {})
        assert content == "test"
        assert result.passed is True
    finally:
        self_review_engine.client = orig_client
        self_review_engine.model = orig_model
