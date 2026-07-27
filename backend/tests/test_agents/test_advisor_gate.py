import sys
import os
import json
import pytest
import logging
from unittest.mock import MagicMock, patch, AsyncMock
import importlib

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import agents.advisor_gate
from agents.advisor_gate import AdvisorGate, AdvisorVerdict, Verdict

# 1. model_registry のインポートエラーフォールバックを検証するテスト
def test_import_error_model_registry(monkeypatch):
    """model_registry が存在しない場合のフォールバック挙動を検証"""
    # 一時的に model_registry インポートを無効化
    monkeypatch.setitem(sys.modules, "model_registry", None)
    # advisor_gate をリロードして except ImportError のルートを通す
    importlib.reload(agents.advisor_gate)
    
    assert agents.advisor_gate.get_model("any_task") == "gemini-2.5-flash"
    
    # 元に戻す
    monkeypatch.delitem(sys.modules, "model_registry")
    importlib.reload(agents.advisor_gate)


# 2. should_review のテスト
def test_should_review():
    """レビュー対象のタスクタイプ判定の境界検証"""
    gate = AdvisorGate()
    # レビュー対象タスク
    assert gate.should_review("smart_cut") is True
    assert gate.should_review("render_final") is True
    assert gate.should_review("youtube_metadata") is True
    assert gate.should_review("council_strategy") is True
    
    # レビュー対象外タスク
    assert gate.should_review("unknown_task") is False
    assert gate.should_review("") is False


# 3. get_review_stats のテスト
def test_get_review_stats():
    """履歴状況に応じたレビュー統計処理の境界検証"""
    gate = AdvisorGate()
    
    # 履歴空の場合
    assert gate.get_review_stats() == {"total_reviews": 0}
    
    # 履歴が存在する場合
    gate.review_history = [
        AdvisorVerdict(verdict="approved", confidence=0.9, reasoning="Good"),
        AdvisorVerdict(verdict="rejected", confidence=0.8, reasoning="Bad"),
        AdvisorVerdict(verdict="approved_with_warnings", confidence=0.7, reasoning="Okay"),
        AdvisorVerdict(verdict="approved", confidence=1.0, reasoning="Perfect")
    ]
    
    stats = gate.get_review_stats()
    assert stats["total_reviews"] == 4
    assert stats["verdicts"]["approved"] == 2
    assert stats["verdicts"]["rejected"] == 1
    assert stats["verdicts"]["approved_with_warnings"] == 1
    assert stats["avg_confidence"] == 0.85
    assert stats["rejection_rate"] == 25.0


# 4. _check_verified_facts のテスト
class MockFact:
    def __init__(self, content):
        self.content = content

def test_check_verified_facts_no_conflict():
    """Verified Facts との衝突がない場合の検証"""
    gate = AdvisorGate()
    
    # 衝突しない提案
    proposed = {"action": "render", "resolution": "1920x1080"}
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.return_value = [
        MockFact("タイトルには固有名詞を含めること"),
        MockFact("無駄なカットを避けること")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 0

def test_check_verified_facts_with_conflict():
    """Verified Facts との衝突がある場合の検証"""
    gate = AdvisorGate()
    
    # JSONのsplit結果と overlap するように key や記号を合わせた提案とファクト
    proposed = {"a": "b", "c": "d"}
    
    mock_store = MagicMock()
    # "避ける" キーワードを含み、かつ '{"a":' と '"c":' が共通ワードとして overlap >= 2 になるようにする
    mock_store.get_facts_by_category.return_value = [
        MockFact('避ける {"a": "c":'),
        MockFact("テスト 用 ファクト")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 1
        assert "Verified Fact と矛盾の可能性" in conflicts[0]

def test_check_verified_facts_exception_fallback():
    """Verified Facts 読み込み例外発生時のフォールバック検証"""
    gate = AdvisorGate()
    
    mock_store = MagicMock()
    # メソッド呼び出し時に例外を投げさせることで except ブロックをカバー
    mock_store.get_facts_by_category.side_effect = ValueError("Database connection error")
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


# 5. _llm_review のテスト (外部APIのモック化)
@pytest.mark.asyncio
async def test_llm_review_success():
    """LLM レビュー正常系の挙動検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "verdict": "approved",
        "confidence": 0.95,
        "reasoning": "すべて成功条件を満たしています。",
        "warnings": [],
        "corrections": []
    })
    mock_client.models.generate_content.return_value = mock_response
    
    mock_store = MagicMock()
    mock_store.get_facts_for_context.return_value = "Verified Context"
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
         patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context={"extra": "data"}
        )
        
        assert result["verdict"] == "approved"
        assert result["confidence"] == 0.95
        assert result["reasoning"] == "すべて成功条件を満たしています。"
        mock_client.models.generate_content.assert_called_once()

@pytest.mark.asyncio
async def test_llm_review_exception_fallback():
    """LLM API 例外発生時のフォールバック境界検証"""
    gate = AdvisorGate()
    
    # Client 取得自体が失敗するケース
    with patch("gemini_client_factory.get_gemini_client", side_effect=ValueError("API Key missing")):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "フォールバック許可" in result["reasoning"]
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]

@pytest.mark.asyncio
async def test_llm_review_json_decode_error():
    """LLM レビューの応答が不正なJSONの場合のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "{invalid json}"
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "LLMレビュー応答パース失敗" in result["reasoning"]
        assert "AdvisorGate LLMレビュー応答の解析に失敗しました" in result["warnings"]


@pytest.mark.asyncio
async def test_llm_review_import_error(monkeypatch):
    """Verified Facts インポート失敗時のフォールバック挙動の検証"""
    gate = AdvisorGate()
    
    # verified_facts のインポートを失敗させる
    monkeypatch.setitem(sys.modules, "agents.memory.verified_facts", None)
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "verdict": "approved",
        "confidence": 0.9,
        "reasoning": "インポートエラーのテスト",
        "warnings": [],
        "corrections": []
    })
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        assert result["verdict"] == "approved"
        assert result["confidence"] == 0.9


# 6. _synthesize_verdict のテスト
def test_synthesize_verdict():
    """判定合成時のルールと制限値の境界検証"""
    gate = AdvisorGate()
    
    # 正常系 (衝突なし)
    llm_verdict = {
        "verdict": "approved",
        "confidence": 0.9,
        "reasoning": "Ok",
        "warnings": ["warning 1"],
        "corrections": []
    }
    result = gate._synthesize_verdict(llm_verdict, [])
    assert result.verdict == "approved"
    assert result.confidence == 0.9
    assert result.verified_facts_conflicts == []
    
    # コンフリクトありの場合のダウングレード検証 (approved -> approved_with_warnings, confidence <= 0.6)
    result_with_conflict = gate._synthesize_verdict(llm_verdict, ["Conflict warning"])
    assert result_with_conflict.verdict == "approved_with_warnings"
    assert result_with_conflict.confidence == 0.6
    assert result_with_conflict.verified_facts_conflicts == ["Conflict warning"]

    # 既に approved 以外の場合のコンフリクトあり検証 (confidence は 0.6 以下に制限されるが、verdict はそのまま)
    llm_verdict_rejected = {
        "verdict": "rejected",
        "confidence": 0.8,
        "reasoning": "No good",
        "warnings": [],
        "corrections": []
    }
    result_rejected = gate._synthesize_verdict(llm_verdict_rejected, ["Conflict warning"])
    assert result_rejected.verdict == "rejected"
    assert result_rejected.confidence == 0.6


# 7. review_before_execution の統合検証
@pytest.mark.asyncio
async def test_review_before_execution_approved():
    """実行前レビュー E2E 的統合テスト (APPROVEDケース)"""
    gate = AdvisorGate()
    
    # llm_review と _check_verified_facts をモック
    mock_llm_verdict = {
        "verdict": "approved",
        "confidence": 0.95,
        "reasoning": "提案に問題はありません。",
        "warnings": [],
        "corrections": []
    }
    
    with patch.object(gate, "_check_verified_facts", return_value=[]) as mock_check, \
         patch.object(gate, "_llm_review", return_value=mock_llm_verdict) as mock_llm:
        
        verdict = await gate.review_before_execution(
            task_description="テストタスク実行",
            proposed_action={"action": "run"},
            definition_of_done="条件A"
        )
        
        assert verdict.verdict == "approved"
        assert verdict.confidence == 0.95
        assert len(gate.review_history) == 1
        assert gate.review_history[0].verdict == "approved"
        mock_check.assert_called_once()
        mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_review_before_execution_rejected():
    """実行前レビュー E2E 的統合テスト (REJECTEDケース)"""
    gate = AdvisorGate()
    
    # llm_review と _check_verified_facts をモック
    mock_llm_verdict = {
        "verdict": "rejected",
        "confidence": 0.85,
        "reasoning": "副作用のリスクがあります。",
        "warnings": ["危険警告"],
        "corrections": [{"field": "action", "current": "run", "suggested": "stop", "reason": "安全のため"}]
    }
    
    with patch.object(gate, "_check_verified_facts", return_value=["Fact conflict"]) as mock_check, \
         patch.object(gate, "_llm_review", return_value=mock_llm_verdict) as mock_llm:
        
        verdict = await gate.review_before_execution(
            task_description="テストタスク危険実行",
            proposed_action={"action": "run_unsafe"},
            definition_of_done="条件B"
        )
        
        assert verdict.verdict == "rejected"
        # 衝突があるため、confidence は min(0.85, 0.6) = 0.6
        assert verdict.confidence == 0.6
        assert verdict.verified_facts_conflicts == ["Fact conflict"]
        assert len(gate.review_history) == 1


# 8. 追加のエッジケース/境界値テスト (カバレッジと信頼性向上のため)
def test_should_review_edge_cases():
    """should_review の引数に特殊な入力が与えられた場合の検証"""
    gate = AdvisorGate()
    assert gate.should_review(None) is False
    assert gate.should_review("   ") is False
    assert gate.should_review("a" * 1000) is False


def test_check_verified_facts_empty_action():
    """proposed_action が空の場合の挙動検証"""
    gate = AdvisorGate()
    assert gate._check_verified_facts({}) == []


def test_synthesize_verdict_missing_fields():
    """llm_verdict に一部 of フィールドが欠落している場合のフォールバック挙動検証"""
    gate = AdvisorGate()
    # 最小限のキーしかない場合
    llm_verdict = {
        "verdict": "approved"
    }
    result = gate._synthesize_verdict(llm_verdict, [])
    assert result.verdict == "approved"
    assert result.confidence == 0.5  # デフォルト値
    assert result.reasoning == ""
    assert result.warnings == []
    assert result.corrections == []


def test_get_review_stats_extreme_confidence():
    """統計処理において confidence が極端な値を取る場合の検証"""
    gate = AdvisorGate()
    gate.review_history = [
        AdvisorVerdict(verdict="approved", confidence=0.0, reasoning="Low"),
        AdvisorVerdict(verdict="approved", confidence=1.0, reasoning="High")
    ]
    stats = gate.get_review_stats()
    assert stats["avg_confidence"] == 0.5
    assert stats["rejection_rate"] == 0.0


@pytest.mark.asyncio
async def test_llm_review_client_none():
    """get_gemini_client() が None を返した場合のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    with patch("gemini_client_factory.get_gemini_client", return_value=None):
        result = await gate._llm_review(
            task_description="テストタスク (Client is None)",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "GOOGLE_API_KEY未設定" in result["reasoning"]
        assert "GOOGLE_API_KEYが設定されていません" in result["warnings"]


def test_check_verified_facts_type_error():
    """proposed_action が json.dumps できないオブジェクトの場合の挙動検証"""
    gate = AdvisorGate()
    # set型はそのまま json.dumps すると TypeError になる
    invalid_action = {"action": {1, 2, 3}}
    
    conflicts = gate._check_verified_facts(invalid_action)
    assert conflicts == []


def test_check_verified_facts_os_error():
    """Verified Facts ストア読み込み時に OSError が発生した場合の挙動検証"""
    gate = AdvisorGate()
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = OSError("Disk read failed")
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []

def test_check_verified_facts_import_error(monkeypatch):
    """Verified Facts 読み込み時に ImportError が発生した場合の挙動検証"""
    gate = AdvisorGate()
    # agents.memory.verified_facts を None に設定してインポート失敗を発生させる
    monkeypatch.setitem(sys.modules, "agents.memory.verified_facts", None)
    conflicts = gate._check_verified_facts({"action": "render"})
    assert conflicts == []


def test_check_verified_facts_json_decode_error():
    """json.dumps 時、あるいは処理中に JSONDecodeError が発生した場合の挙動検証"""
    gate = AdvisorGate()
    with patch("json.dumps", side_effect=json.JSONDecodeError("mock msg", "{}", 0)):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []

# ============================================================
# T-batch_10609a-bug_hunter-004 で追加された具体的な例外検証
# ============================================================

def test_check_verified_facts_attribute_error_fallback():
    """Verified Facts 読み込み時に AttributeError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = AttributeError("Mock attribute error")
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


def test_check_verified_facts_value_error_fallback():
    """Verified Facts 読み込み時に ValueError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = ValueError("Mock value error")
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


@pytest.mark.asyncio
async def test_llm_review_api_error_fallback():
    """LLM API で APIError が発生した場合のフォールバック検証"""
    from google.genai.errors import APIError
    gate = AdvisorGate()
    # APIError は適切な引数でモック
    api_error = APIError(code=500, response_json={"message": "Mock API Error"})
    with patch("gemini_client_factory.get_gemini_client", side_effect=api_error):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


@pytest.mark.asyncio
async def test_llm_review_runtime_error_fallback():
    """LLM API で RuntimeError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    with patch("gemini_client_factory.get_gemini_client", side_effect=RuntimeError("Mock runtime error")):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD条件",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


# ============================================================
# T-batch_8aae8d-bug_hunter-001 で追加された多言語/日本語・英語の衝突検出テスト
# ============================================================

def test_check_verified_facts_japanese_conflict():
    """日本語の Verified Facts との衝突判定の検証（スペースなし日本語）"""
    gate = AdvisorGate()
    
    # 衝突する提案 (タイトルに "4K" が入っており、かつ同義語で "タイトル" -> "title" がマッチし、"4K" もマッチする)
    proposed = {"action": "set_title", "title": "春の4K特別映像"}
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.return_value = [
        MockFact("タイトルに 4K という文字を使わないこと")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 1
        assert "Verified Fact と矛盾の可能性: タイトルに 4K という文字を使わないこと" in conflicts[0]


def test_check_verified_facts_japanese_no_conflict():
    """日本語の Verified Facts との非衝突判定の検証"""
    gate = AdvisorGate()
    
    # 衝突しない提案（タイトルではなく、説明文などの別項目）
    proposed = {"action": "set_metadata", "description": "田中太郎の冒険"}
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.return_value = [
        MockFact("タイトルに 4K という文字を使わないこと")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 0


def test_check_verified_facts_english_conflict():
    """英語の Verified Facts との衝突判定の検証"""
    gate = AdvisorGate()
    
    # 衝突する提案 (render, low, quality などのキーワードが重なる)
    proposed = {"action": "render", "quality": "low", "resolution": "360p"}
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.return_value = [
        MockFact("avoid low quality render")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 1
        assert "Verified Fact と矛盾の可能性: avoid low quality render" in conflicts[0]


# ============================================================
# T-batch_c6f9d8-bug_hunter-002 で追加されたテスト
# ============================================================

@pytest.mark.asyncio
async def test_llm_review_import_error_google_genai(monkeypatch):
    """google.genai インポート失敗時、UnboundLocalError にならず正しくフォールバックされるか検証"""
    # google.genai 関連のインポートを失敗させる
    monkeypatch.setitem(sys.modules, "google.genai", None)
    monkeypatch.setitem(sys.modules, "google.genai.errors", None)

    gate = AdvisorGate()
    result = await gate._llm_review(
        task_description="テストタスク (google.genai インポートエラー)",
        proposed_action={"action": "test"},
        definition_of_done="DoD",
        context=None
    )
    assert result["verdict"] == "approved_with_warnings"
    assert result["confidence"] == 0.5
    assert "google-genaiがインストールされていません" in result["warnings"]


@pytest.mark.asyncio
async def test_llm_review_proposed_action_type_error():
    """proposed_action が JSON シリアライズ不可能なオブジェクトを含む場合でも、クラッシュせず LLM 呼び出しへ進むか検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "verdict": "approved",
        "confidence": 0.9,
        "reasoning": "シリアライズ失敗からのフォールバック検証",
        "warnings": [],
        "corrections": []
    })
    mock_client.models.generate_content.return_value = mock_response

    # proposed_action に set型（シリアライズ不可）を含める
    unserializable_action = {"action": {1, 2, 3}}

    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="シリアライズ失敗テスト",
            proposed_action=unserializable_action,
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved"
        assert result["confidence"] == 0.9


@pytest.mark.asyncio
async def test_llm_review_empty_response_text():
    """API の応答テキストが空（None または空文字）のとき、TypeError を起こさずにフォールバックされるか検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = None  # 空レスポンス
    mock_client.models.generate_content.return_value = mock_response

    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="空レスポンステスト",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


# ============================================================
# カバレッジ向上テスト
# ============================================================

def test_check_verified_facts_empty_keywords():
    """ファクトに禁止用語しか含まれずキーワードリストが空になる場合の continue 分岐を検証"""
    gate = AdvisorGate()
    proposed = {"action": "render"}
    
    mock_store = MagicMock()
    # "避ける" と "NG" は両方 stop_words なので keywords は空になる
    mock_store.get_facts_by_category.return_value = [
        MockFact("避ける NG")
    ]
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts(proposed)
        assert len(conflicts) == 0


def test_check_verified_facts_type_error_serialization():
    """proposed_action 内のオブジェクトが文字列変換時に TypeError を投げる場合のハンドリングを検証"""
    gate = AdvisorGate()
    
    class BadStringClass:
        def __str__(self):
            raise TypeError("String conversion failed")
            
    proposed = {"action": BadStringClass()}
    
    # 例外が発生するはずだが、TypeError キャッチで空リストが返ることを確認
    conflicts = gate._check_verified_facts(proposed)
    assert conflicts == []


# ============================================================
# 例外処理リファクタリング検証用追加テスト
# ============================================================

def test_check_verified_facts_key_error_fallback():
    """_check_verified_facts 内で KeyError が発生した際のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    mock_store = MagicMock()
    # get_facts_by_category 呼び出し時に KeyError を投げる
    mock_store.get_facts_by_category.side_effect = KeyError("Mocked KeyError")
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


def test_check_verified_facts_index_error_fallback():
    """_check_verified_facts 内で IndexError が発生した際のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    mock_store = MagicMock()
    # get_facts_by_category 呼び出し時に IndexError を投げる
    mock_store.get_facts_by_category.side_effect = IndexError("Mocked IndexError")
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


@pytest.mark.asyncio
async def test_llm_review_attribute_error_fallback():
    """_llm_review 内で AttributeError が発生した際のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = AttributeError("Mocked AttributeError")
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


@pytest.mark.asyncio
async def test_llm_review_key_error_fallback():
    """_llm_review 内で KeyError が発生した際のフォールバック挙動を検証"""
    gate = AdvisorGate()
    
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = KeyError("Mocked KeyError")
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


def test_technical_debt_store_register_debt_failure_safety():
    """technical_debt_store.register_debt 呼び出し失敗時に advisor_gate がクラッシュしないことを検証"""
    gate = AdvisorGate()
    
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = KeyError("Trigger error for technical debt registration")
    
    mock_td_store = MagicMock()
    mock_td_store.register_debt.side_effect = AttributeError("Mocked register_debt failure")
    
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store), \
         patch("agents.memory.technical_debt.technical_debt_store", mock_td_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


def test_check_verified_facts_name_error_fallback():
    """Verified Facts 読み込み時に NameError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = NameError("Mock NameError")
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


def test_check_verified_facts_runtime_error_fallback():
    """Verified Facts 読み込み時に RuntimeError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = RuntimeError("Mock RuntimeError")
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


@pytest.mark.asyncio
async def test_llm_review_name_error_fallback():
    """LLM レビュー中に NameError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    with patch("gemini_client_factory.get_gemini_client", side_effect=NameError("Mock NameError")):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


@pytest.mark.asyncio
async def test_llm_review_os_error_fallback_fatal():
    """LLM レビュー中に OSError が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    with patch("gemini_client_factory.get_gemini_client", side_effect=OSError("Mock OSError")):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


def test_import_error_model_registry_general_exception(monkeypatch):
    """model_registry インポート時に TypeError など予期せぬ例外が発生した場合のフォールバック挙動を検証"""
    class BadModule:
        @property
        def get_model(self):
            raise TypeError("Mocked TypeError during import/attribute access")

    monkeypatch.setitem(sys.modules, "model_registry", BadModule())
    importlib.reload(agents.advisor_gate)
    
    assert agents.advisor_gate.get_model("any_task") == "gemini-2.5-flash"
    
    # 元に戻す
    monkeypatch.delitem(sys.modules, "model_registry")
    importlib.reload(agents.advisor_gate)


def test_advisor_verdict_enum_normalization():
    """AdvisorVerdict 初期化時に verdict に Enum を渡しても文字列に正規化されることを検証"""
    verdict_enum = Verdict.APPROVED
    verdict = AdvisorVerdict(
        verdict=verdict_enum,
        confidence=0.9,
        reasoning="Enum test"
    )
    assert verdict.verdict == "approved"
    assert isinstance(verdict.verdict, str)

    # 整数などのその他の型も文字列に変換されることを検証
    verdict_int = AdvisorVerdict(
        verdict=123,
        confidence=0.8,
        reasoning="Integer test"
    )
    assert verdict_int.verdict == "123"
    assert isinstance(verdict_int.verdict, str)


def test_check_verified_facts_unexpected_exception_fallback():
    """Verified Facts 読み込み時に予期せぬ例外(例: ZeroDivisionError)が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    mock_store = MagicMock()
    mock_store.get_facts_by_category.side_effect = ZeroDivisionError("Mock ZeroDivisionError")
    with patch("agents.memory.verified_facts.verified_facts_store", mock_store):
        conflicts = gate._check_verified_facts({"action": "render"})
        assert conflicts == []


@pytest.mark.asyncio
async def test_llm_review_unexpected_exception_fallback():
    """LLM レビュー中に予期せぬ例外(例: ZeroDivisionError)が発生した場合のフォールバック検証"""
    gate = AdvisorGate()
    with patch("gemini_client_factory.get_gemini_client", side_effect=ZeroDivisionError("Mock ZeroDivisionError")):
        result = await gate._llm_review(
            task_description="テストタスク",
            proposed_action={"action": "test"},
            definition_of_done="DoD",
            context=None
        )
        assert result["verdict"] == "approved_with_warnings"
        assert result["confidence"] == 0.5
        assert "AdvisorGate LLMレビューが実行できませんでした" in result["warnings"]


