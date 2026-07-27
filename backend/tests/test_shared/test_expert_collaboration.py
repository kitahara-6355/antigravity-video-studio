import pytest
import asyncio
from typing import Dict, Any
from agents.expert_collaboration import (
    CouncilContext,
    new_context,
    collaborate,
    collaborate_parallel,
    collaborate_async,
)

class DummyAgent:
    def __init__(self, name: str, stance: str = "NEUTRAL", summary: str = "Test", should_fail: bool = False):
        self.name = name
        self.stance = stance
        self.summary = summary
        self.should_fail = should_fail
        self.calls = []

    def process(self, input_data: Dict[str, Any], config: Dict[str, Any], council_context: Any = None) -> Dict[str, Any]:
        self.calls.append((input_data, config, council_context))
        if self.should_fail:
            raise RuntimeError(f"Dummy agent {self.name} failed")
        return {"stance": self.stance, "summary": self.summary}

def test_council_context():
    ctx = new_context()
    assert isinstance(ctx, CouncilContext)
    
    ctx.post_finding("AgentA", "Insight from AgentA")
    findings = ctx.get_findings()
    assert findings == {"AgentA": "Insight from AgentA"}
    
    ctx.clear()
    assert ctx.get_findings() == {}

def test_collaborate_sequential():
    agent1 = DummyAgent("Agent1", "SUPPORT", "Good idea")
    agent2 = DummyAgent("Agent2", "OPPOSE", "Bad idea")
    agents = [agent1, agent2]
    
    results = collaborate(agents, "Should we do this?")
    assert len(results) == 2
    assert results[0] == {"stance": "SUPPORT", "summary": "Good idea"}
    
    # Verify findings posted
    ctx = CouncilContext()
    collaborate(agents, "Should we do this?", ctx=ctx)
    findings = ctx.get_findings()
    assert findings["Agent1"] == "SUPPORT: Good idea"
    assert findings["Agent2"] == "OPPOSE: Bad idea"

def test_collaborate_sequential_with_exceptions():
    agent1 = DummyAgent("Agent1", should_fail=True)
    agent2 = DummyAgent("Agent2", "SUPPORT", "Good idea")
    agents = [agent1, agent2]
    
    ctx = CouncilContext()
    # It should not raise an exception because of try-except block
    results = collaborate(agents, "Query", ctx=ctx)
    assert len(results) == 1  # only Agent2 succeeds in Pass 2
    assert results[0] == {"stance": "SUPPORT", "summary": "Good idea"}
    assert "Agent1" not in ctx.get_findings()
    assert ctx.get_findings()["Agent2"] == "SUPPORT: Good idea"

def test_collaborate_parallel():
    agent1 = DummyAgent("Agent1", "SUPPORT", "Agree")
    agent2 = DummyAgent("Agent2", "OPPOSE", "Disagree")
    agents = [agent1, agent2]
    
    res = collaborate_parallel(agents, "Query")
    assert "responses" in res
    assert "findings" in res
    assert "meta" in res
    assert res["responses"]["Agent1"] == {"stance": "SUPPORT", "summary": "Agree"}
    assert res["findings"]["Agent2"] == "OPPOSE: Disagree"
    assert res["meta"]["agent_count"] == 2

def test_collaborate_parallel_with_exceptions():
    agent1 = DummyAgent("Agent1", should_fail=True)
    agent2 = DummyAgent("Agent2", "SUPPORT", "Agree")
    agents = [agent1, agent2]
    
    res = collaborate_parallel(agents, "Query")
    # Even if agent1 fails, it should return gracefully
    assert "Agent1" in res["responses"]
    assert "error" in res["responses"]["Agent1"]
    assert res["responses"]["Agent2"] == {"stance": "SUPPORT", "summary": "Agree"}
    assert res["findings"]["Agent1"] == "ERROR"

@pytest.mark.asyncio
async def test_collaborate_async():
    agent1 = DummyAgent("Agent1", "SUPPORT", "Agree")
    agent2 = DummyAgent("Agent2", "OPPOSE", "Disagree")
    agents = [agent1, agent2]
    
    res = await collaborate_async(agents, "Query")
    assert res["responses"]["Agent1"] == {"stance": "SUPPORT", "summary": "Agree"}
    assert res["findings"]["Agent2"] == "OPPOSE: Disagree"
    assert res["meta"]["async"] is True

@pytest.mark.asyncio
async def test_collaborate_async_with_exceptions():
    agent1 = DummyAgent("Agent1", should_fail=True)
    agent2 = DummyAgent("Agent2", "SUPPORT", "Agree")
    agents = [agent1, agent2]
    
    res = await collaborate_async(agents, "Query")
    # exceptions should be caught by asyncio.gather(return_exceptions=True) and ignored
    assert "Agent1" not in res["responses"]
    assert res["responses"]["Agent2"] == {"stance": "SUPPORT", "summary": "Agree"}
    assert "Agent1" not in res["findings"]

def test_council_context_shared_variables_and_timestamp():
    import time
    ctx = new_context()
    # shared_variables
    ctx.data["shared_variables"]["key1"] = "val1"
    assert ctx.data["shared_variables"]["key1"] == "val1"

    # timestamp update
    t1 = ctx.data["last_update"]
    time.sleep(0.01)
    ctx.post_finding("AgentA", "Test")
    t2 = ctx.data["last_update"]
    assert t2 > t1

    time.sleep(0.01)
    ctx.clear()
    t3 = ctx.data["last_update"]
    assert t3 > t2

@pytest.mark.asyncio
async def test_collaborate_empty_agents():
    # test sequential
    res_seq = collaborate([], "query")
    assert res_seq == []

    # test parallel
    res_par = collaborate_parallel([], "query")
    assert res_par["responses"] == {}
    assert res_par["findings"] == {}
    assert res_par["meta"]["agent_count"] == 0

    # test async
    res_async = await collaborate_async([], "query")
    assert res_async["responses"] == {}
    assert res_async["findings"] == {}

@pytest.mark.asyncio
async def test_collaborate_multiple_exceptions():
    agent1 = DummyAgent("Agent1", should_fail=True)
    agent2 = DummyAgent("Agent2", should_fail=True)
    agent3 = DummyAgent("Agent3", "SUPPORT", "Agree")
    agents = [agent1, agent2, agent3]

    # test sequential
    res_seq = collaborate(agents, "query")
    assert len(res_seq) == 1
    assert res_seq[0] == {"stance": "SUPPORT", "summary": "Agree"}

    # test parallel
    res_par = collaborate_parallel(agents, "query")
    assert "Agent1" in res_par["responses"]
    assert "error" in res_par["responses"]["Agent1"]
    assert "Agent2" in res_par["responses"]
    assert "error" in res_par["responses"]["Agent2"]
    assert res_par["responses"]["Agent3"] == {"stance": "SUPPORT", "summary": "Agree"}

    # test async
    res_async = await collaborate_async(agents, "query")
    assert "Agent1" not in res_async["responses"]
    assert "Agent2" not in res_async["responses"]
    assert res_async["responses"]["Agent3"] == {"stance": "SUPPORT", "summary": "Agree"}


def test_collaboration_exception_logging(caplog):
    import logging
    agent1 = DummyAgent("Agent1", should_fail=True)
    agents = [agent1]

    # test sequential logging
    with caplog.at_level(logging.WARNING):
        collaborate(agents, "query")
        assert any("Sequential collaboration error in Agent1 Pass 1" in record.message for record in caplog.records)
        assert any("Sequential collaboration error in Agent1 Pass 2" in record.message for record in caplog.records)

    caplog.clear()

    # test parallel logging
    with caplog.at_level(logging.WARNING):
        collaborate_parallel(agents, "query")
        assert any("Parallel collaboration error in Agent1 Pass 1" in record.message for record in caplog.records)
        assert any("Parallel collaboration error in Agent1 Pass 2" in record.message for record in caplog.records)


def test_extract_finding_edge_cases():
    from agents.expert_collaboration import _extract_finding
    # 空辞書
    assert _extract_finding({}) == "NEUTRAL: "
    # 片方のキーのみ存在
    assert _extract_finding({"stance": "SUPPORT"}) == "SUPPORT: "
    assert _extract_finding({"summary": "Brief summary"}) == "NEUTRAL: Brief summary"
    # stanceとsummaryが両方存在
    assert _extract_finding({"stance": "OPPOSE", "summary": "Bad idea"}) == "OPPOSE: Bad idea"
    # 不正な値の型
    with pytest.raises(AttributeError):
        _extract_finding(None)  # type: ignore
    with pytest.raises(AttributeError):
        _extract_finding(123)  # type: ignore


def test_council_context_edge_cases():
    import time
    ctx = CouncilContext()
    # 空文字列や巨大な文字列の post_finding
    ctx.post_finding("", "")
    assert ctx.get_findings()[""] == ""

    large_text = "A" * 10000
    ctx.post_finding("LargeAgent", large_text)
    assert ctx.get_findings()["LargeAgent"] == large_text

    # 同一エージェント名の上書き検証
    ctx.post_finding("AgentA", "Insight 1")
    t1 = ctx.data["last_update"]
    time.sleep(0.001)
    ctx.post_finding("AgentA", "Insight 2")
    t2 = ctx.data["last_update"]
    assert ctx.get_findings()["AgentA"] == "Insight 2"
    assert t2 >= t1


class MalformedAgent:
    def __init__(self, name: str):
        self.name = name
    # processメソッドを持たない


class InvalidResponseAgent:
    def __init__(self, name: str, return_val: Any):
        self.name = name
        self.return_val = return_val

    def process(self, input_data: Dict[str, Any], config: Dict[str, Any], council_context: Any = None) -> Any:
        return self.return_val


def test_collaborate_edge_cases():
    # user_queryにNone, 空文字列, 巨大文字列を渡す
    agent1 = DummyAgent("Agent1")
    assert len(collaborate([agent1], "")) == 1
    assert len(collaborate([agent1], "A" * 10000)) == 1

    # agentsにprocessメソッドを持たないエージェントが含まれている場合
    agent_bad = MalformedAgent("BadAgent")
    res = collaborate([agent_bad, agent1], "Query")
    # 例外が内部でキャッチされ、クラッシュしないことを確認
    # agent1は無事に動作する
    assert len(res) == 1

    # agentsのprocessが辞書以外の無効な型を返す場合
    agent_invalid_res = InvalidResponseAgent("InvalidAgent", "not a dict")
    # _extract_finding(res)でAttributeErrorが発生するが、それがSequential collaboration errorとしてキャッチされる
    # 一方で、Pass 2では戻り値がそのまま結果リストに追加される
    res = collaborate([agent_invalid_res, agent1], "Query")
    assert len(res) == 2
    assert res[0] == "not a dict"
    assert res[1] == {"stance": "NEUTRAL", "summary": "Test"}


def test_collaborate_parallel_edge_cases():
    agent_bad = MalformedAgent("BadAgent")
    agent_invalid_res = InvalidResponseAgent("InvalidAgent", 12345)
    agent1 = DummyAgent("Agent1")

    # agentsリストに異常オブジェクト混入時の挙動
    res = collaborate_parallel([agent_bad, agent_invalid_res, agent1], "Query")
    # 例外がスレッド内で発生しても、それぞれエラー辞書で返される
    assert "BadAgent" in res["responses"]
    assert "error" in res["responses"]["BadAgent"]

    # InvalidResponseAgent は Pass 1 で例外になるが、Pass 2 は正常に 12345 を返す
    assert res["responses"]["InvalidAgent"] == 12345

    assert res["responses"]["Agent1"] == {"stance": "NEUTRAL", "summary": "Test"}

    # findingsの確認
    assert res["findings"]["BadAgent"] == "ERROR"
    assert res["findings"]["InvalidAgent"] == "ERROR"
    assert res["findings"]["Agent1"] == "NEUTRAL: Test"


@pytest.mark.asyncio
async def test_collaborate_async_edge_cases():
    agent_bad = MalformedAgent("BadAgent")
    agent1 = DummyAgent("Agent1")

    # agentsに異常オブジェクト混入
    # MalformedAgent は process メソッドを持たないため _process_async で例外を投げるが、
    # asyncio.gather(return_exceptions=True) により無視され、結果には含まれない
    res = await collaborate_async([agent_bad, agent1], "Query")
    assert "BadAgent" not in res["responses"]
    assert res["responses"]["Agent1"] == {"stance": "NEUTRAL", "summary": "Test"}

    assert "BadAgent" not in res["findings"]
    assert res["findings"]["Agent1"] == "NEUTRAL: Test"

    # process が None を返す場合、_extract_finding(None) により AttributeError が発生する
    # これは関数全体から送出されるはず
    agent_invalid_res = InvalidResponseAgent("InvalidAgent", None)
    with pytest.raises(AttributeError):
        await collaborate_async([agent_invalid_res, agent1], "Query")


def test_council_context_invalid_types():
    ctx = new_context()
    # 不正な型を渡した場合の挙動を検証
    # Pythonの辞書自体はキーと値に多様な型を許容するため、例外は発生しない
    ctx.post_finding(None, None)  # type: ignore
    assert ctx.get_findings()[None] is None  # type: ignore

    ctx.post_finding(123, 456)  # type: ignore
    assert ctx.get_findings()[123] == 456  # type: ignore


def test_collaborate_with_none_agents():
    # agents リスト内に None が混在している場合のエッジケース
    # プロダクションコードでは、exceptブロック内で agent.name を参照しようとして AttributeError が発生する
    agent1 = DummyAgent("Agent1")
    
    with pytest.raises(AttributeError) as exc_info:
        collaborate([agent1, None, DummyAgent("Agent2")], "Query")
    assert "'NoneType' object has no attribute 'name'" in str(exc_info.value)


def test_collaborate_parallel_with_none_agents():
    agent1 = DummyAgent("Agent1")
    # プロダクションコードでは、_process_parallel_pass1のexceptブロック内で agent.name を参照しようとして AttributeError が発生する
    with pytest.raises(AttributeError) as exc_info:
        collaborate_parallel([agent1, None, DummyAgent("Agent2")], "Query")
    assert "'NoneType' object has no attribute 'name'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_collaborate_async_with_none_agents():
    agent1 = DummyAgent("Agent1")
    # 非同期実行 (collaborate_async)
    # None の要素は _process_async の中で AttributeError を投げるが、
    # asyncio.gather(return_exceptions=True) により無視され、結果には含まれない
    # （_process_async 内では agent.name を参照する前に例外が返され、
    #  さらに gather の中で例外がキャッチされるため、クラッシュしない）
    res = await collaborate_async([agent1, None, DummyAgent("Agent2")], "Query")
    assert "Agent1" in res["responses"]
    assert None not in res["responses"]
    assert res["responses"]["Agent1"] == {"stance": "NEUTRAL", "summary": "Test"}


def test_collaborate_invalid_query():
    # user_query が None の場合
    agent1 = DummyAgent("Agent1")
    res = collaborate([agent1], None)  # type: ignore
    assert len(res) == 1
    assert res[0] == {"stance": "NEUTRAL", "summary": "Test"}
    assert agent1.calls[0][0] == {"text": None}


@pytest.mark.asyncio
async def test_collaborate_agents_none():
    # agents が None の場合、collaborate (逐次) は TypeError を投げる
    with pytest.raises(TypeError):
        collaborate(None, "Query")  # type: ignore

    # collaborate_parallel / collaborate_async は if not agents: で正常終了する
    res_par = collaborate_parallel(None, "Query")  # type: ignore
    assert res_par["responses"] == {}
    assert res_par["meta"]["agent_count"] == 0

    res_async = await collaborate_async(None, "Query")  # type: ignore
    assert res_async["responses"] == {}
    assert res_async["meta"]["async"] is True



