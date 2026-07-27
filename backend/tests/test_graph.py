import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.graph import run_graph


@pytest.mark.asyncio
async def test_run_graph_invalid_query_none():
    """query が None の場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="query must be a non-empty string."):
        await run_graph(query=None)


@pytest.mark.asyncio
async def test_run_graph_invalid_query_type():
    """query が文字列でない場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="query must be a non-empty string."):
        await run_graph(query=123)  # type: ignore


@pytest.mark.asyncio
async def test_run_graph_invalid_query_empty():
    """query が空文字列または空白のみの場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="query must be a non-empty string."):
        await run_graph(query="")
    with pytest.raises(ValueError, match="query must be a non-empty string."):
        await run_graph(query="   ")


@pytest.mark.asyncio
async def test_run_graph_invalid_council_mode():
    """council_mode が無効な値の場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="council_mode must be 'pre_production' or 'post_production'."):
        await run_graph(query="valid query", council_mode="invalid_mode")


@pytest.mark.asyncio
async def test_run_graph_invalid_session_id_type():
    """session_id が None でなく、かつ文字列でない場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="session_id must be a non-empty string if provided."):
        await run_graph(query="valid query", session_id=123)  # type: ignore


@pytest.mark.asyncio
async def test_run_graph_invalid_session_id_empty():
    """session_id が空文字列または空白のみの場合に ValueError が送出されること"""
    with pytest.raises(ValueError, match="session_id must be a non-empty string if provided."):
        await run_graph(query="valid query", session_id="")
    with pytest.raises(ValueError, match="session_id must be a non-empty string if provided."):
        await run_graph(query="valid query", session_id="   ")


@pytest.mark.asyncio
@patch("agents.graph.run_council", new_callable=AsyncMock)
async def test_run_graph_success_default(mock_run_council):
    """デフォルト値で run_council が正しく呼び出され、返り値が一致すること"""
    expected_response = {"status": "success", "data": "test"}
    mock_run_council.return_value = expected_response

    result = await run_graph(query="hello")

    mock_run_council.assert_called_once_with(
        user_query="hello",
        council_mode="post_production",
        session_id=None,
    )
    assert result == expected_response


@pytest.mark.asyncio
@patch("agents.graph.run_council", new_callable=AsyncMock)
async def test_run_graph_success_with_session_id(mock_run_council):
    """指定された引数が run_council に正しく伝播されること"""
    expected_response = {"status": "success", "data": "custom"}
    mock_run_council.return_value = expected_response

    result = await run_graph(
        query="hello",
        council_mode="pre_production",
        session_id="session-456",
    )

    mock_run_council.assert_called_once_with(
        user_query="hello",
        council_mode="pre_production",
        session_id="session-456",
    )
    assert result == expected_response


@pytest.mark.asyncio
@patch("agents.graph.run_council", new_callable=AsyncMock)
@patch("agents.memory.technical_debt.technical_debt_store")
async def test_run_graph_unexpected_exception(mock_td_store, mock_run_council):
    """予期せぬ例外が発生した際、TDR登録が行われ、かつ例外が再送出されること"""
    mock_run_council.side_effect = RuntimeError("Something went wrong")

    with pytest.raises(RuntimeError, match="Something went wrong"):
        await run_graph(query="hello")

    mock_td_store.register_debt.assert_called_once_with(
        category="MINOR_INFRA",
        file_path="backend/agents/graph.py",
        line_number=49,
        pattern="except Exception as e: in run_graph",
        cause_pattern="DP-01",
        fix_pattern="例外の再送出",
        registered_by="thumbnail_task_22",
        notes="run_graphで想定外のエラーが発生: Something went wrong",
    )


@pytest.mark.asyncio
@patch("agents.graph.run_council", new_callable=AsyncMock)
@patch("agents.memory.technical_debt.technical_debt_store")
async def test_run_graph_tdr_registration_failure(mock_td_store, mock_run_council):
    """TDR登録自体が失敗した場合でも、元の例外が確実に再送出されること"""
    mock_run_council.side_effect = RuntimeError("Original error")
    mock_td_store.register_debt.side_effect = Exception("TDR registration failed")

    with pytest.raises(RuntimeError, match="Original error"):
        await run_graph(query="hello")

    mock_td_store.register_debt.assert_called_once()


@pytest.mark.asyncio
@patch("agents.graph.run_council", new_callable=AsyncMock)
@patch("agents.memory.technical_debt.technical_debt_store")
async def test_run_graph_delegate_value_error(mock_td_store, mock_run_council):
    """run_council から ValueError がスローされた場合、TDR登録を行わず、そのまま例外が再送出されること"""
    mock_run_council.side_effect = ValueError("Delegate ValueError")

    with pytest.raises(ValueError, match="Delegate ValueError"):
        await run_graph(query="hello")

    mock_td_store.register_debt.assert_not_called()


def test_graph_exports():
    """agents.graph が互換性のために必要な関数やオブジェクトを再エクスポートしていることを検証"""
    import agents.graph as graph_module
    from agents.council_graph import run_council, _fallback_response

    assert hasattr(graph_module, "run_council")
    assert graph_module.run_council is run_council

    assert hasattr(graph_module, "_fallback_response")
    assert graph_module._fallback_response is _fallback_response
