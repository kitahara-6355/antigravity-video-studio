import sys
import json
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# backend ディレクトリを sys.path に追加して、中のモジュールが正しくインポートできるようにする
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# テスト対象のモジュール
import self_review_engine
from self_review_engine import (
    SelfReviewEngine,
    QualityScore,
    ReviewResult,
    ImprovementRecord,
    review_generation,
    review_and_improve,
    advisor_then_review
)

@pytest.fixture
def mock_gemini_client():
    client = MagicMock()
    response = MagicMock()
    response.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    client.models.generate_content.return_value = response
    return client

# 1. 憲法ファイルが存在する場合としない場合の初期化
def test_load_constitution_exists():
    mock_data = '{"rule": "value"}'
    with patch("builtins.open", mock_open(read_data=mock_data)), \
         patch("self_review_engine.Path.exists", return_value=True), \
         patch("self_review_engine.get_gemini_client"), \
         patch("self_review_engine.get_model"):
        engine = SelfReviewEngine()
        assert engine.constitution == {"rule": "value"}

def test_load_constitution_not_exists():
    with patch("self_review_engine.Path.exists", return_value=False), \
         patch("self_review_engine.get_gemini_client"), \
         patch("self_review_engine.get_model"):
        engine = SelfReviewEngine()
        assert engine.constitution == {}

# 2. _parse_review メソッド
def test_parse_review_normal_passed():
    engine = self_review_engine.self_review_engine
    text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    result = engine._parse_review(text)
    assert result.passed is True
    assert result.score.context_fit == 0.9
    assert result.score.constitution_fit == 0.9
    assert result.score.technical_quality == 0.9
    assert result.score.overall == 0.9
    assert result.issues == []
    assert result.suggestions == []

def test_parse_review_normal_failed():
    engine = self_review_engine.self_review_engine
    # 閾値: context_fit >= 0.70, constitution_fit >= 0.80, technical_quality >= 0.60, overall >= 0.70
    text = '{"context_fit": 0.65, "constitution_fit": 0.90, "technical_quality": 0.90, "issues": ["issue"], "suggestions": ["suggest"]}'
    result = engine._parse_review(text)
    assert result.passed is False
    assert result.score.context_fit == 0.65
    assert result.issues == ["issue"]
    assert result.suggestions == ["suggest"]

def test_parse_review_json_decode_error():
    engine = self_review_engine.self_review_engine
    text = '{invalid json}'
    result = engine._parse_review(text)
    assert result.passed is True
    assert result.score.overall == 0.75

def test_parse_review_no_json_match():
    engine = self_review_engine.self_review_engine
    text = 'no json at all'
    result = engine._parse_review(text)
    assert result.passed is True
    assert result.score.overall == 0.75

def test_parse_review_missing_keys():
    engine = self_review_engine.self_review_engine
    text = '{}'
    result = engine._parse_review(text)
    assert result.passed is False
    assert result.score.context_fit == 0.5
    assert result.score.constitution_fit == 0.5
    assert result.score.technical_quality == 0.5
    assert result.score.overall == 0.5

# 3. review メソッド
def test_review_success(mock_gemini_client):
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        result = engine.review("content", "type", {"ctx": "val"})
        assert result.passed is True
        assert result.score.overall == 0.9

def test_review_exception(mock_gemini_client):
    mock_gemini_client.models.generate_content.side_effect = Exception("LLM error")
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        result = engine.review("content", "type", {"ctx": "val"})
        assert result.passed is True
        assert result.score.overall == 0.75

# 4. review_and_improve メソッド
def test_review_and_improve_passed_immediately(mock_gemini_client):
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        improved_content, result = engine.review_and_improve("content", "type", {"ctx": "val"})
        assert improved_content == "content"
        assert result.passed is True
        assert result.improvement_applied is False
        assert len(result.improvement_history) == 0

def test_review_and_improve_with_custom_improve(mock_gemini_client):
    response_fail = MagicMock()
    response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    response_pass = MagicMock()
    response_pass.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    
    mock_gemini_client.models.generate_content.side_effect = [response_fail, response_pass]
    
    custom_improve = MagicMock(return_value="improved content")
    
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        improved_content, result = engine.review_and_improve("content", "type", {"ctx": "val"}, improve_func=custom_improve)
        assert improved_content == "improved content"
        assert result.passed is True
        assert result.improvement_applied is True
        assert len(result.improvement_history) == 1
        assert result.improvement_history[0]["round"] == 1
        assert result.improvement_history[0]["original_score"] == 0.5
        custom_improve.assert_called_once_with("content", ["bad"], ["fix"])

def test_review_and_improve_max_rounds_reached(mock_gemini_client):
    response_fail = MagicMock()
    response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    
    mock_gemini_client.models.generate_content.side_effect = [response_fail, response_fail, response_fail, response_fail]
    
    custom_improve = MagicMock(side_effect=lambda content, issues, suggestions: content + " improved")
    
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        improved_content, result = engine.review_and_improve("content", "type", {"ctx": "val"}, improve_func=custom_improve)
        assert improved_content == "content improved improved improved"
        assert result.passed is False
        assert result.improvement_applied is True
        assert len(result.improvement_history) == 3

def test_review_and_improve_default_improve_success(mock_gemini_client):
    response_fail = MagicMock()
    response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    response_improve = MagicMock()
    response_improve.text = "default improved content"
    response_pass = MagicMock()
    response_pass.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    
    mock_gemini_client.models.generate_content.side_effect = [
        response_fail,
        response_improve,
        response_pass
    ]
    
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        improved_content, result = engine.review_and_improve("content", "type", {"ctx": "val"})
        assert improved_content == "default improved content"
        assert result.passed is True
        assert result.improvement_applied is True

def test_review_and_improve_default_improve_exception(mock_gemini_client):
    response_fail = MagicMock()
    response_fail.text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": ["bad"], "suggestions": ["fix"]}'
    response_pass = MagicMock()
    response_pass.text = '{"context_fit": 0.9, "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    
    mock_gemini_client.models.generate_content.side_effect = [
        response_fail,
        Exception("LLM error during improve"),
        response_pass
    ]
    
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        improved_content, result = engine.review_and_improve("content", "type", {"ctx": "val"})
        assert improved_content == "content"
        assert result.passed is True
        assert result.improvement_applied is True

# 5. advisor_then_review 非同期関数
@pytest.mark.asyncio
async def test_advisor_then_review_import_error():
    with patch.dict("sys.modules", {"agents.advisor_gate": None}), \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        mock_review_and_improve.return_value = ("result", "result_obj")
        res = await advisor_then_review("content", "type", {"ctx": "val"})
        assert res == ("result", "result_obj")
        mock_review_and_improve.assert_called_once_with("content", "type", {"ctx": "val"})

@pytest.mark.asyncio
async def test_advisor_then_review_should_not_review():
    mock_advisor_gate = MagicMock()
    mock_advisor_gate.should_review.return_value = False
    
    mock_module = MagicMock()
    mock_module.advisor_gate = mock_advisor_gate
    
    with patch.dict("sys.modules", {"agents.advisor_gate": mock_module}), \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        mock_review_and_improve.return_value = ("result", "result_obj")
        res = await advisor_then_review("content", "type", {"ctx": "val"})
        assert res == ("result", "result_obj")
        mock_advisor_gate.should_review.assert_called_once_with("type")
        mock_review_and_improve.assert_called_once_with("content", "type", {"ctx": "val"})

@pytest.mark.asyncio
async def test_advisor_then_review_should_review_passed():
    mock_advisor_gate = MagicMock()
    mock_advisor_gate.should_review.return_value = True
    
    mock_verdict = MagicMock()
    mock_verdict.verdict = 'approved'
    async def mock_review_before_execution(*args, **kwargs):
        return mock_verdict
    mock_advisor_gate.review_before_execution = mock_review_before_execution
    
    mock_module = MagicMock()
    mock_module.advisor_gate = mock_advisor_gate
    
    with patch.dict("sys.modules", {"agents.advisor_gate": mock_module}), \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        mock_review_and_improve.return_value = ("result", "result_obj")
        res = await advisor_then_review("content", "type", {"ctx": "val"})
        assert res == ("result", "result_obj")
        mock_review_and_improve.assert_called_once_with("content", "type", {"ctx": "val"})

@pytest.mark.asyncio
async def test_advisor_then_review_should_review_rejected():
    mock_advisor_gate = MagicMock()
    mock_advisor_gate.should_review.return_value = True
    
    mock_verdict = MagicMock()
    mock_verdict.verdict = 'rejected'
    mock_verdict.reasoning = 'insufficient quality'
    mock_verdict.corrections = [{'suggested': 'do X'}]
    async def mock_review_before_execution(*args, **kwargs):
        return mock_verdict
    mock_advisor_gate.review_before_execution = mock_review_before_execution
    
    mock_module = MagicMock()
    mock_module.advisor_gate = mock_advisor_gate
    
    with patch.dict("sys.modules", {"agents.advisor_gate": mock_module}), \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        res_content, res_result = await advisor_then_review("content", "type", {"ctx": "val"})
        assert res_content == "content"
        assert res_result.passed is False
        assert res_result.score.overall == 0
        assert res_result.issues == ['AdvisorGate rejected: insufficient quality']
        assert res_result.suggestions == ['do X']
        mock_review_and_improve.assert_not_called()

@pytest.mark.asyncio
async def test_advisor_then_review_exception():
    mock_advisor_gate = MagicMock()
    mock_advisor_gate.should_review.side_effect = Exception("Advisor error")
    
    mock_module = MagicMock()
    mock_module.advisor_gate = mock_advisor_gate
    
    with patch.dict("sys.modules", {"agents.advisor_gate": mock_module}), \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        mock_review_and_improve.return_value = ("result", "result_obj")
        res = await advisor_then_review("content", "type", {"ctx": "val"})
        assert res == ("result", "result_obj")
        mock_review_and_improve.assert_called_once_with("content", "type", {"ctx": "val"})

# 6. 簡易関数と ImprovementRecord ラムダ式カバー
def test_helper_functions():
    with patch.object(self_review_engine.self_review_engine, "review") as mock_review, \
         patch.object(self_review_engine.self_review_engine, "review_and_improve") as mock_review_and_improve:
        mock_review.return_value = "review_res"
        mock_review_and_improve.return_value = ("improved", "review_res")
        
        res1 = review_generation("content", "type", {"ctx": "val"})
        res2 = review_and_improve("content", "type", {"ctx": "val"})
        
        assert res1 == "review_res"
        assert res2 == ("improved", "review_res")
        mock_review.assert_called_once_with("content", "type", {"ctx": "val"})
        mock_review_and_improve.assert_called_once_with("content", "type", {"ctx": "val"})

def test_improvement_record_timestamp():
    record = ImprovementRecord(
        round=1,
        original_score=0.5,
        improved_score=0.9,
        changes_made=["changed"]
    )
    assert record.timestamp is not None
    assert isinstance(record.timestamp, str)
    assert len(record.timestamp) > 0


def test_parse_review_null_issues_and_suggestions():
    engine = self_review_engine.self_review_engine
    text = '{"context_fit": 0.5, "constitution_fit": 0.5, "technical_quality": 0.5, "issues": null, "suggestions": null}'
    result = engine._parse_review(text)
    assert result.passed is False
    assert result.issues == []
    assert result.suggestions == []
    
    # _default_improve が issues=None/suggestions=None の場合に TypeError にならずに実行されることを確認
    with patch.object(engine, "client") as mock_client:
        mock_client.models.generate_content.side_effect = Exception("API error")
        improved = engine._default_improve("some content", result, {})
        assert improved == "some content"


def test_parse_review_string_scores():
    engine = self_review_engine.self_review_engine
    text = '{"context_fit": "0.9", "constitution_fit": "0.9", "technical_quality": "0.9", "issues": [], "suggestions": []}'
    result = engine._parse_review(text)
    assert result.passed is True
    assert result.score.context_fit == 0.9
    assert result.score.overall == 0.9

    # 無効な文字列スコアの場合
    text_invalid = '{"context_fit": "bad_score", "constitution_fit": 0.9, "technical_quality": 0.9, "issues": [], "suggestions": []}'
    result_invalid = engine._parse_review(text_invalid)
    assert result_invalid.passed is True
    assert result_invalid.score.overall == 0.75  # fallback


def test_review_null_response_text(mock_gemini_client):
    mock_gemini_client.models.generate_content.return_value.text = None
    with patch("self_review_engine.get_gemini_client", return_value=mock_gemini_client):
        engine = SelfReviewEngine()
        result = engine.review("content", "type", {"ctx": "val"})
        assert result.passed is True
        assert result.score.overall == 0.75  # fallback

