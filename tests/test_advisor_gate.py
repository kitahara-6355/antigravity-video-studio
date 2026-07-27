import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import json
import logging
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from agents.advisor_gate import AdvisorGate, AdvisorVerdict, Verdict

# ロギング設定
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_gemini_client():
    with patch("gemini_client_factory.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_verified_facts():
    with patch("agents.memory.verified_facts.verified_facts_store") as mock_store:
        yield mock_store


def test_advisor_gate_initialization():
    """AdvisorGateの初期化と基本メソッドの検証"""
    gate = AdvisorGate(reviewer_model="test-model")
    assert gate.reviewer_model == "test-model"
    assert len(gate.review_history) == 0

    # should_review の確認
    assert gate.should_review("smart_cut") is True
    assert gate.should_review("render_final") is True
    assert gate.should_review("unknown_task") is False


def test_check_verified_facts_no_conflict(mock_verified_facts):
    """Verified Factsチェックで衝突がない場合"""
    # モックのファクトを設定
    mock_fact = MagicMock()
    mock_fact.content = "タイトルに『警告』の文字を使用するのを避ける"
    mock_fact.category = "preference"
    mock_verified_facts.get_facts_by_category.return_value = [mock_fact]

    gate = AdvisorGate()
    proposed_action = {
        "title": "通常のタイトル",
        "action": "render"
    }
    
    conflicts = gate._check_verified_facts(proposed_action)
    assert len(conflicts) == 0


def test_check_verified_facts_with_conflict(mock_verified_facts):
    """Verified Factsチェックで衝突がある場合"""
    mock_fact = MagicMock()
    mock_fact.content = "タイトルに『警告』の文字を使用するのを避ける"
    mock_fact.category = "preference"
    mock_verified_facts.get_facts_by_category.return_value = [mock_fact]

    gate = AdvisorGate()
    
    # "タイトル" と "避ける" から抽出されたキーワード "タイトル" が "title" (synonyms経由) にヒットする
    # かつ "警告" というキーワードが proposed_action 内に含まれることで衝突とする
    proposed_action = {
        "title": "警告付きのタイトル",
        "action": "render"
    }
    
    conflicts = gate._check_verified_facts(proposed_action)
    assert len(conflicts) > 0
    assert "Verified Fact と矛盾の可能性" in conflicts[0]


@pytest.mark.asyncio
async def test_llm_review_success(mock_gemini_client):
    """LLMレビューが正常にJSONを返した場合の検証"""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "verdict": "approved",
        "confidence": 0.95,
        "reasoning": "提案アクションは適切です",
        "warnings": [],
        "corrections": []
    })
    mock_gemini_client.models.generate_content.return_value = mock_response

    gate = AdvisorGate()
    verdict = await gate._llm_review(
        task_description="Test Task",
        proposed_action={"action": "test"},
        definition_of_done="DOD",
        context={}
    )

    assert verdict["verdict"] == "approved"
    assert verdict["confidence"] == 0.95
    assert verdict["reasoning"] == "提案アクションは適切です"


@pytest.mark.asyncio
async def test_llm_review_invalid_json(mock_gemini_client):
    """LLMが不正なJSONを返した場合にフォールバックされること"""
    mock_response = MagicMock()
    mock_response.text = "invalid json text"
    mock_gemini_client.models.generate_content.return_value = mock_response

    gate = AdvisorGate()
    verdict = await gate._llm_review(
        task_description="Test Task",
        proposed_action={"action": "test"},
        definition_of_done="DOD",
        context={}
    )

    assert verdict["verdict"] == "approved_with_warnings"
    assert verdict["confidence"] == 0.5
    assert "LLMレビュー応答パース失敗" in verdict["reasoning"]
    assert "AdvisorGate LLMレビュー応答の解析に失敗しました" in verdict["warnings"]


@pytest.mark.asyncio
async def test_llm_review_api_error(mock_gemini_client):
    """APIError や RuntimeError が発生した場合にフォールバックされること"""
    mock_gemini_client.models.generate_content.side_effect = RuntimeError("API Call Failed")

    gate = AdvisorGate()
    verdict = await gate._llm_review(
        task_description="Test Task",
        proposed_action={"action": "test"},
        definition_of_done="DOD",
        context={}
    )

    assert verdict["verdict"] == "approved_with_warnings"
    assert verdict["confidence"] == 0.5
    assert "LLMレビュー失敗のためフォールバック許可" in verdict["reasoning"]
    assert "AdvisorGate LLMレビューが実行できませんでした" in verdict["warnings"]


def test_synthesize_verdict():
    """LLM レビューと Verified Facts の競合が正しく合成されること"""
    gate = AdvisorGate()
    
    # 競合なし
    llm_verdict = {
        "verdict": "approved",
        "confidence": 0.9,
        "reasoning": "Good",
        "warnings": [],
        "corrections": []
    }
    res = gate._synthesize_verdict(llm_verdict, [])
    assert res.verdict == "approved"
    assert res.confidence == 0.9

    # 競合ありの場合は approved -> approved_with_warnings になり confidence が制限される
    res_conflict = gate._synthesize_verdict(llm_verdict, ["Conflict fact"])
    assert res_conflict.verdict == "approved_with_warnings"
    assert res_conflict.confidence == 0.6
    assert res_conflict.verified_facts_conflicts == ["Conflict fact"]


@pytest.mark.asyncio
async def test_review_before_execution_full(mock_gemini_client, mock_verified_facts):
    """review_before_execution ライフサイクル全体のテスト"""
    mock_fact = MagicMock()
    mock_fact.content = "タイトルに『警告』の文字を使用するのを避ける"
    mock_fact.category = "preference"
    mock_verified_facts.get_facts_by_category.return_value = [mock_fact]

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "verdict": "approved",
        "confidence": 0.95,
        "reasoning": "提案は成功条件を満たします",
        "warnings": [],
        "corrections": []
    })
    mock_gemini_client.models.generate_content.return_value = mock_response

    gate = AdvisorGate()
    
    # 衝突ありのアクション
    proposed_action = {
        "title": "警告付きタイトル",
        "action": "smart_cut"
    }

    verdict = await gate.review_before_execution(
        task_description="SmartCutで構成決定",
        proposed_action=proposed_action,
        definition_of_done="DOD"
    )

    # synthesize によって approved -> approved_with_warnings となるはず
    assert verdict.verdict == "approved_with_warnings"
    assert verdict.confidence == 0.6
    assert len(verdict.verified_facts_conflicts) == 1
    assert len(gate.review_history) == 1

    # 統計情報の確認
    stats = gate.get_review_stats()
    assert stats["total_reviews"] == 1
    assert stats["avg_confidence"] == 0.6
    assert stats["rejection_rate"] == 0.0


@pytest.mark.asyncio
async def test_check_verified_facts_unexpected_exception(mock_verified_facts):
    """_check_verified_facts で未知の例外が発生した場合、安全にキャッチされ技術負債が登録されること"""
    mock_verified_facts.get_facts_by_category.side_effect = ZeroDivisionError("division by zero")

    gate = AdvisorGate()
    
    with patch("agents.memory.technical_debt.technical_debt_store.register_debt") as mock_register:
        conflicts = gate._check_verified_facts({"action": "test"})
        assert len(conflicts) == 0  # エラー時は衝突なしとしてフォールバック
        mock_register.assert_called_once()
        _, kwargs = mock_register.call_args
        assert kwargs["category"] == "ACCEPTED_SAFETY"
        assert kwargs["cause_pattern"] == "DP-02"


@pytest.mark.asyncio
async def test_llm_review_unexpected_exception(mock_gemini_client):
    """_llm_review で未知の例外が発生した場合、安全にフォールバックされ技術負債が登録されること"""
    mock_gemini_client.models.generate_content.side_effect = ZeroDivisionError("division by zero")

    gate = AdvisorGate()
    
    with patch("agents.memory.technical_debt.technical_debt_store.register_debt") as mock_register:
        verdict = await gate._llm_review(
            task_description="Test Task",
            proposed_action={"action": "test"},
            definition_of_done="DOD",
            context={}
        )

        assert verdict["verdict"] == "approved_with_warnings"
        assert verdict["confidence"] == 0.5
        assert "LLMレビューで未知の致命的エラー発生のためフォールバック許可" in verdict["reasoning"]
        mock_register.assert_called_once()
        _, kwargs = mock_register.call_args
        assert kwargs["category"] == "ACCEPTED_SAFETY"
        assert kwargs["cause_pattern"] == "DP-02"


def test_get_review_stats_calculation():
    """get_review_stats が複数件の異なる判定結果に対して正しく集計・計算を行うことの検証"""
    gate = AdvisorGate()
    
    # 履歴を手動で注入
    gate.review_history = [
        AdvisorVerdict(verdict="approved", confidence=0.8, reasoning="Ok"),
        AdvisorVerdict(verdict="approved_with_warnings", confidence=0.6, reasoning="Warning"),
        AdvisorVerdict(verdict="rejected", confidence=0.4, reasoning="No"),
        AdvisorVerdict(verdict="rejected", confidence=0.2, reasoning="No 2"),
    ]
    
    stats = gate.get_review_stats()
    
    assert stats["total_reviews"] == 4
    assert stats["verdicts"]["approved"] == 1
    assert stats["verdicts"]["approved_with_warnings"] == 1
    assert stats["verdicts"]["rejected"] == 2
    # avg_confidence = (0.8 + 0.6 + 0.4 + 0.2) / 4 = 2.0 / 4 = 0.5
    assert stats["avg_confidence"] == 0.5
    # rejection_rate = 2 / 4 * 100 = 50.0%
    assert stats["rejection_rate"] == 50.0


def test_get_review_stats_invalid_confidence():
    """confidence に不正な値（Noneや文字列）が含まれている場合でもクラッシュせず計算できることの検証"""
    gate = AdvisorGate()
    gate.review_history = [
        AdvisorVerdict(verdict="approved", confidence=0.8, reasoning="Ok"),
        AdvisorVerdict(verdict="approved_with_warnings", confidence="invalid_float", reasoning="Warning"),
        AdvisorVerdict(verdict="rejected", confidence=None, reasoning="No"),
    ]
    
    stats = gate.get_review_stats()
    assert stats["total_reviews"] == 3
    # 0.8 + 0.5 (fallback) + 0.5 (fallback) = 1.8. 1.8 / 3 = 0.6
    assert stats["avg_confidence"] == 0.6


def test_synthesize_verdict_invalid_type():
    """_synthesize_verdict に dict ではない llm_verdict が渡された場合でも安全にフォールバックされること"""
    gate = AdvisorGate()
    res = gate._synthesize_verdict("invalid_type_string", [])
    assert res.verdict == "approved_with_warnings"
    assert res.confidence == 0.5
    assert res.reasoning == ""


@pytest.mark.asyncio
async def test_llm_review_expected_key_error(mock_gemini_client):
    """_llm_review で KeyError や AttributeError が発生した場合に catchable_exceptions として処理されること"""
    # models.generate_content が呼び出された際に KeyError を投げるように設定
    mock_gemini_client.models.generate_content.side_effect = KeyError("Mocked KeyError")

    gate = AdvisorGate()
    with patch("agents.memory.technical_debt.technical_debt_store.register_debt") as mock_register:
        verdict = await gate._llm_review(
            task_description="Test Task",
            proposed_action={"action": "test"},
            definition_of_done="DOD",
            context={}
        )
        assert verdict["verdict"] == "approved_with_warnings"
        assert verdict["confidence"] == 0.5
        assert "LLMレビュー失敗のためフォールバック許可" in verdict["reasoning"]
        # catchable_exceptions に含まれているため、技術負債の登録（except Exception）は行われない
        mock_register.assert_not_called()


def test_check_verified_facts_re_error(mock_verified_facts):
    """_check_verified_facts で re.error や KeyError が発生した場合、適切にキャッチされクラッシュしないこと"""
    mock_fact = MagicMock()
    mock_fact.content = "テストコンテンツ"
    mock_verified_facts.get_facts_by_category.return_value = [mock_fact]

    gate = AdvisorGate()
    
    import re
    with patch("re.findall", side_effect=re.error("mocked re.error")):
        with patch("agents.memory.technical_debt.technical_debt_store.register_debt") as mock_register:
            conflicts = gate._check_verified_facts({"action": "test"})
            assert len(conflicts) == 0
            # re.error は明示的にキャッチされ、except Exception に到達しないため技術負債は登録されない
            mock_register.assert_not_called()
