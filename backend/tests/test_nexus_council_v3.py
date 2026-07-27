import asyncio
import pytest
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any, List

from backend.agents.nexus_council_v3 import (
    InputGuardrail,
    QuantitativeMapping,
    SafetyFallback,
    IntentAnalyzer,
    TaskBreakdownEngine,
    run_nexus_council_v3,
)

# ==============================================================
# 1. InputGuardrail Tests
# ==============================================================

def test_input_guardrail_none():
    with pytest.raises(ValueError, match="クエリが指定されていません。"):
        InputGuardrail.validate_query(None)

def test_input_guardrail_empty():
    with pytest.raises(ValueError, match="クエリが空、または空白のみです。"):
        InputGuardrail.validate_query("   ")

def test_input_guardrail_too_long():
    too_long_query = "a" * 2001
    with pytest.raises(ValueError, match="クエリが制限（2000文字）を超えています。"):
        InputGuardrail.validate_query(too_long_query)

def test_input_guardrail_suspicious_patterns():
    suspicious_queries = [
        "System.exit(0)",
        "import os; os.system('ls')",
        "subprocess.run('cmd')",
        "eval('1+1')",
        "exec('print(1)')",
        "<html><script>alert(1)</script></html>",
    ]
    for q in suspicious_queries:
        with pytest.raises(ValueError, match="不審な文字パターンが検出されました。"):
            InputGuardrail.validate_query(q)

def test_input_guardrail_valid():
    valid_query = "   分析を行ってください。   "
    result = InputGuardrail.validate_query(valid_query)
    assert result == "分析を行ってください。"


# ==============================================================
# 2. QuantitativeMapping Tests
# ==============================================================

def test_quantitative_mapping_short():
    res = QuantitativeMapping.resolve_parameters("短いクエリ")
    assert res["timeout_seconds"] == 10.0
    assert res["max_iterations"] == 2
    assert res["complexity_level"] == "NORMAL"

def test_quantitative_mapping_medium():
    res = QuantitativeMapping.resolve_parameters("これは中くらいの長さのクエリです。特に複雑なキーワードを含んでいません。")
    assert res["timeout_seconds"] == 20.0
    assert res["max_iterations"] == 3
    assert res["complexity_level"] == "NORMAL"

def test_quantitative_mapping_long():
    long_query = "これは非常に長いクエリです。" * 10
    res = QuantitativeMapping.resolve_parameters(long_query)
    assert res["timeout_seconds"] == 30.0
    assert res["max_iterations"] == 5
    assert res["complexity_level"] == "HIGH"

def test_quantitative_mapping_complex_keyword():
    # 短いクエリだが複雑キーワードあり
    res = QuantitativeMapping.resolve_parameters("詳細な分析")
    # timeout: 10 + 5 = 15.0, max_iterations: 2 + 1 = 3
    assert res["timeout_seconds"] == 15.0
    assert res["max_iterations"] == 3
    assert res["complexity_level"] == "HIGH"

    # 長いクエリ（100文字以上）で複雑キーワードあり
    long_complex = "これは非常に長いクエリで、さらに詳細な分析を含みます。" * 5
    res2 = QuantitativeMapping.resolve_parameters(long_complex)
    # timeout: 30 (max 30), max_iterations: 5 (max 5)
    assert res2["timeout_seconds"] == 30.0
    assert res2["max_iterations"] == 5
    assert res2["complexity_level"] == "HIGH"


# ==============================================================
# 3. IntentAnalyzer Tests
# ==============================================================

def test_intent_analyzer_analyst():
    assert "Analyst" in IntentAnalyzer.analyze_experts("維持率データの分析")
    assert "Analyst" in IntentAnalyzer.analyze_experts("CTRを上げたい")
    assert "Analyst" in IntentAnalyzer.analyze_experts("視聴数データ")

def test_intent_analyzer_strategist():
    assert "Strategist" in IntentAnalyzer.analyze_experts("中長期的な成長戦略")
    assert "Strategist" in IntentAnalyzer.analyze_experts("ロードマップを策定")

def test_intent_analyzer_director():
    assert "Director" in IntentAnalyzer.analyze_experts("サムネイルのデザイン")
    assert "Director" in IntentAnalyzer.analyze_experts("編集の演出")

def test_intent_analyzer_all():
    experts = IntentAnalyzer.analyze_experts("何でもない質問")
    assert set(experts) == {"Analyst", "Strategist", "Director"}


# ==============================================================
# 4. TaskBreakdownEngine Tests
# ==============================================================

def test_task_breakdown_empty():
    assert TaskBreakdownEngine.extract_tasks("") == ["タスク1: 詳細なアクションプランの策定"]
    assert TaskBreakdownEngine.extract_tasks(None) == ["タスク1: 詳細なアクションプランの策定"]

def test_task_breakdown_parse_bullets():
    synthesis = "提案内容:\n\n- タスクAを実行する\n\n* タスクBを実行する\n• タスクCを実行する"
    tasks = TaskBreakdownEngine.extract_tasks(synthesis)
    assert "タスクAを実行する" in tasks
    assert "タスクBを実行する" in tasks
    assert "タスクCを実行する" in tasks

def test_task_breakdown_parse_numbered():
    synthesis = "提案内容:\n1. 演出のブラッシュアップ\n2) 音量の均一化"
    tasks = TaskBreakdownEngine.extract_tasks(synthesis)
    assert "演出のブラッシュアップ" in tasks
    assert "音量の均一化" in tasks

def test_task_breakdown_parse_prefix():
    synthesis = "提案内容:\nタスク1: サムネイル作成\nタスク2： テロップの修正"
    tasks = TaskBreakdownEngine.extract_tasks(synthesis)
    assert "タスク: サムネイル作成" in tasks
    assert "タスク: テロップの修正" in tasks

def test_task_breakdown_fallback():
    synthesis = "箇条書きなどのタスクらしき記述が含まれない普通の文章です。これに対する処理。"
    tasks = TaskBreakdownEngine.extract_tasks(synthesis)
    assert len(tasks) == 2
    assert "タスク1: 統合レポートに示された提案事項の具現化" in tasks


# ==============================================================
# 5. SafetyFallback Tests
# ==============================================================

def test_safety_fallback_timeout():
    res = SafetyFallback.generate_response("テストクエリ", "タイムアウト発生")
    assert res["status"] == "fallback_2_party"
    assert "テストクエリ" in res["synthesis"]
    assert "タイムアウト" in res["synthesis"]
    assert len(res["debate_flow"]) == 2
    assert res["debate_flow"][0]["agent"] == "Strategist"
    assert res["debate_flow"][1]["agent"] == "Director"
    assert "Director主導による演出構成の即時反映" in res["tasks"][0]
    assert res["session_id"].startswith("fallback-")

def test_safety_fallback_general_error():
    res = SafetyFallback.generate_response("テストクエリ", "例外発生")
    assert res["status"] == "fallback"
    assert "テストクエリ" in res["synthesis"]
    assert "例外発生" in res["synthesis"]
    assert len(res["debate_flow"]) == 1
    assert res["debate_flow"][0]["agent"] == "Strategist"
    assert len(res["tasks"]) == 2
    assert res["session_id"].startswith("fallback-")

    res2 = SafetyFallback.generate_response("テストクエリ", "例外発生", "specific-session-id")
    assert res2["session_id"] == "specific-session-id"


# ==============================================================
# 6. run_nexus_council_v3 Tests (Async)
# ==============================================================

@pytest.mark.asyncio
async def test_run_nexus_council_v3_success():
    async def mock_runner(query, experts, max_iterations):
        return "合成結果:\n- タスクAの実行\n- タスクBの実行", [
            {"agent": "Analyst", "summary": "分析しました"}
        ]
        
    res = await run_nexus_council_v3("動画の分析をお願いします", "session-123", mock_runner)
    assert res["status"] == "success"
    assert res["session_id"] == "session-123"
    assert "合成結果" in res["synthesis"]
    assert "タスクAの実行" in res["tasks"]
    assert res["debate_flow"][0]["agent"] == "Analyst"

@pytest.mark.asyncio
async def test_run_nexus_council_v3_guardrail_failed():
    # 不正なクエリ
    with pytest.raises(ValueError, match="不審な文字パターン"):
        await run_nexus_council_v3("import os", "session-456")

@pytest.mark.asyncio
async def test_run_nexus_council_v3_runner_exception():
    async def mock_runner_exception(query, experts, max_iterations):
        raise RuntimeError("LLM接続不可")

    res = await run_nexus_council_v3("戦略の提案", "session-789", mock_runner_exception)
    assert res["status"] == "fallback"
    assert "内部例外: LLM接続不可" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_nexus_council_v3_timeout():
    async def mock_runner_slow(query, experts, max_iterations):
        await asyncio.sleep(2.0)
        return "遅い合成結果", []

    # タイムアウトを引き起こすために一時的に QuantitativeMapping の timeout_seconds をモック
    with patch("backend.agents.nexus_council_v3.QuantitativeMapping.resolve_parameters") as mock_resolve:
        mock_resolve.return_value = {
            "timeout_seconds": 0.1,  # 0.1秒でタイムアウト
            "max_iterations": 2,
            "complexity_level": "NORMAL"
        }
        res = await run_nexus_council_v3("短い質問", "session-timeout", mock_runner_slow)
        assert res["status"] == "fallback_2_party"
        assert "タイムアウト" in res["synthesis"]
        assert "スキップ" in res["synthesis"]
        assert any(t["agent"] == "Director" for t in res["debate_flow"])

@pytest.mark.asyncio
async def test_run_nexus_council_v3_real_adk_absent():
    # 本番動作パスにおける google-adk インポートエラーをシミュレート
    with patch.dict(sys.modules, {"google.adk.runners": None}):
        res = await run_nexus_council_v3("戦略の提案", "session-no-adk")
        assert res["status"] == "fallback"
        assert "Google ADK ライブラリ不在" in res["synthesis"]

@pytest.mark.asyncio
async def test_run_nexus_council_v3_real_adk_present_flow():
    # 本番動作パスで google-adk がある場合（モック経由）のフローテスト
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_part = MagicMock()
    mock_part.text = "合成された提言です。\n1. アクションプラン"
    mock_event.content.parts = [mock_part]
    
    async def mock_run_async(*args, **kwargs):
        yield mock_event

    mock_runner_instance.run_async = mock_run_async

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance, create=True), \
         patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())), \
         patch("google.adk.agents.run_config.RunConfig", create=True), \
         patch("google.genai.types.Content", create=True), \
         patch("google.genai.types.Part", create=True):
         
         res = await run_nexus_council_v3("演出と編集の戦略", "session-adk-flow")
         assert res["status"] == "success"
         assert "合成された提言です。" in res["synthesis"]
         assert "アクションプラン" in res["tasks"]

@pytest.mark.asyncio
async def test_run_nexus_council_v3_real_adk_present_empty_response():
    # ADKからの最終応答が空で、セッションステートから合成テキストを取得するケース
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    # 応答を空にする
    async def mock_run_async_empty(*args, **kwargs):
        # yields nothing
        if False:
            yield None

    mock_runner_instance.run_async = mock_run_async_empty
    
    # セッションステートからのフォールバック取得用
    mock_session = MagicMock()
    mock_session.state = {"council_synthesis": "セッションから取得した提言。\n- タスクX"}
    mock_session_service.get_session.return_value = mock_session

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance, create=True), \
         patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())), \
         patch("google.adk.agents.run_config.RunConfig", create=True), \
         patch("google.genai.types.Content", create=True), \
         patch("google.genai.types.Part", create=True):
         
         res = await run_nexus_council_v3("演出の相談", "session-adk-empty-res")
         assert res["status"] == "success"
         assert "セッションから取得した提言。" in res["synthesis"]
         assert "タスクX" in res["tasks"]

@pytest.mark.asyncio
async def test_run_nexus_council_v3_real_adk_present_both_empty_error():
    # 応答もステートも空で例外が発生するケース
    mock_runner_instance = MagicMock()
    mock_session_service = AsyncMock()
    mock_runner_instance.session_service = mock_session_service
    
    async def mock_run_async_empty(*args, **kwargs):
        if False:
            yield None

    mock_runner_instance.run_async = mock_run_async_empty
    
    # ステートも空
    mock_session = MagicMock()
    mock_session.state = {}
    mock_session_service.get_session.return_value = mock_session

    with patch("google.adk.runners.InMemoryRunner", return_value=mock_runner_instance, create=True), \
         patch("agents.council_graph._build_council_agents", return_value=(MagicMock(), MagicMock(), MagicMock(), MagicMock())), \
         patch("google.adk.agents.run_config.RunConfig", create=True), \
         patch("google.genai.types.Content", create=True), \
         patch("google.genai.types.Part", create=True):
         
         res = await run_nexus_council_v3("演出の相談", "session-adk-both-empty")
         # エラーが発生して、SafetyFallback が動作するはず
         assert res["status"] == "fallback"
         assert "内部例外: ADKからの応答が空でした。" in res["synthesis"]
