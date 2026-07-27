import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from agents.graph import run_graph, _fallback_response

@pytest.mark.asyncio
async def test_run_graph_success():
    """run_graph が council_graph.run_council に正しく委譲することを確認する"""
    mock_response = {
        "synthesis": "テスト結果レポートです。",
        "session_id": "test-session-123",
        "status": "success"
    }
    
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.return_value = mock_response
        
        result = await run_graph(
            query="テスト用のクエリ",
            council_mode="pre_production",
            session_id="test-session-123"
        )
        
        # 戻り値の検証
        assert result == mock_response
        
        # 引数の検証
        mock_run_council.assert_called_once_with(
            user_query="テスト用のクエリ",
            council_mode="pre_production",
            session_id="test-session-123"
        )

@pytest.mark.asyncio
async def test_run_graph_defaults():
    """run_graph がデフォルト引数で正しく動作することを確認する"""
    mock_response = {
        "synthesis": "デフォルト引数のテスト結果です。",
        "session_id": "test-session-456",
        "status": "success"
    }
    
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.return_value = mock_response
        
        result = await run_graph(query="シンプルなクエリ")
        
        # 戻り値の検証
        assert result == mock_response
        
        # デフォルト引数が渡されているかの検証
        mock_run_council.assert_called_once_with(
            user_query="シンプルなクエリ",
            council_mode="post_production",
            session_id=None
        )

def test_fallback_response_export():
    """_fallback_response が agents.graph からエクスポートされていることを確認する"""
    assert _fallback_response is not None
    # 実際に _fallback_response を呼び出して動作確認
    res = _fallback_response("エラークエリ", "モックエラー")
    assert res["status"] == "error"
    assert "モックエラー" in res["synthesis"]


@pytest.mark.asyncio
async def test_run_graph_exception():
    """run_council が例外を発生させた場合に、run_graph がその例外をそのまま伝播することを確認する"""
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.side_effect = ValueError("ADK runner configuration error")
        
        with pytest.raises(ValueError, match="ADK runner configuration error"):
            await run_graph(query="例外クエリ")


@pytest.mark.asyncio
async def test_run_graph_logging(caplog):
    """run_graph が呼び出された際に、期待されるログ出力が行われることを確認する"""
    mock_response = {"synthesis": "ログテスト結果", "session_id": "log-sess", "status": "success"}
    
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.return_value = mock_response
        
        with caplog.at_level("INFO"):
            await run_graph(query="ログテスト用", council_mode="pre_production")
            
        assert any(
            "[graph.py] run_graph" in record.message and "mode=pre_production" in record.message
            for record in caplog.records
        )

# --- ここから新規追加の堅牢化テスト ---

@pytest.mark.asyncio
async def test_run_graph_validation_query():
    """query引数のバリデーション（None, 非文字列, 空文字）で ValueError が発生することを確認する"""
    for invalid_query in [None, 123, "", "   "]:
        with pytest.raises(ValueError, match="query must be a non-empty string."):
            await run_graph(query=invalid_query)

@pytest.mark.asyncio
async def test_run_graph_validation_mode():
    """council_modeのバリデーション（無効なモード）で ValueError が発生することを確認する"""
    for invalid_mode in [None, "invalid_mode", "production"]:
        with pytest.raises(ValueError, match="council_mode must be 'pre_production' or 'post_production'."):
            await run_graph(query="有効なクエリ", council_mode=invalid_mode)

@pytest.mark.asyncio
async def test_run_graph_validation_session_id():
    """session_idが渡された際のバリデーション（空文字列等）で ValueError が発生することを確認する"""
    for invalid_session in ["", "   ", 123]:
        with pytest.raises(ValueError, match="session_id must be a non-empty string if provided."):
            await run_graph(query="有効なクエリ", session_id=invalid_session)

@pytest.mark.asyncio
async def test_run_graph_unexpected_exception_tdr_registration():
    """想定外の例外が発生した際に、TDR (TechnicalDebtStore) に自動登録され、かつ例外が再送出されることを確認する"""
    # run_council が RuntimeError (想定外の例外) を投げるようにモックする
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.side_effect = RuntimeError("ADK runner crashed unexpectedly")
        
        # TechnicalDebtStore.register_debt をモックして、呼び出しを追跡する
        with patch("agents.memory.technical_debt.technical_debt_store.register_debt", new_callable=MagicMock) as mock_register_debt:
            
            with pytest.raises(RuntimeError, match="ADK runner crashed unexpectedly"):
                await run_graph(query="テストクエリ")
            
            # register_debt が呼び出されたことを確認
            mock_register_debt.assert_called_once()
            
            # 呼び出し引数の検証
            args, kwargs = mock_register_debt.call_args
            assert kwargs.get("category") == "MINOR_INFRA"
            assert kwargs.get("file_path") == "backend/agents/graph.py"
            assert "except Exception as e: in run_graph" in kwargs.get("pattern", "")
            assert "crashed unexpectedly" in kwargs.get("notes", "")


@pytest.mark.asyncio
async def test_run_graph_unexpected_exception_tdr_registration_failure(caplog):
    """TDRへの登録自体が失敗した場合でも、元の例外が正しく再送出されることを確認する"""
    with patch("agents.graph.run_council", new_callable=AsyncMock) as mock_run_council:
        mock_run_council.side_effect = RuntimeError("ADK runner crashed unexpectedly")
        
        with patch("agents.memory.technical_debt.technical_debt_store.register_debt", new_callable=MagicMock) as mock_register_debt:
            mock_register_debt.side_effect = Exception("TDR store database locked")
            
            with caplog.at_level("ERROR"):
                with pytest.raises(RuntimeError, match="ADK runner crashed unexpectedly"):
                    await run_graph(query="テストクエリ")
            
            assert any(
                "Failed to register debt in run_graph: TDR store database locked" in record.message
                for record in caplog.records
            )

