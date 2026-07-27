import pytest
from unittest.mock import MagicMock, patch
import json
import sys
import os
from google.genai.errors import APIError

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents._deprecated.supervisor import SupervisorAgent, Route

def test_init_success():
    """正常初期化テスト"""
    mock_client = MagicMock()
    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client),          patch("agents._deprecated.supervisor.get_model", return_value="mock-supervisor-model"):
        
        agent = SupervisorAgent()
        assert agent.client == mock_client
        assert agent.model_name == "mock-supervisor-model"

def test_route_recursion_limit():
    """メッセージ履歴が10を超える場合に再帰リミットガードが働き、FINISHを返すことを検証"""
    mock_client = MagicMock()
    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client):
        agent = SupervisorAgent()
        # 11個のメッセージ
        messages = [MagicMock(content=f"msg_{i}") for i in range(11)]
        res = agent.route(messages)
        assert res.next == "FINISH"
        assert "Recursion limit" in res.reason
        # APIは呼ばれていないはず
        mock_client.models.generate_content.assert_not_called()

def test_route_success():
    """正常系: APIが適切なJSONを返し、Routeオブジェクトに正しくマッピングされること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "next": "Analyst",
        "reason": "初期段階なので競合調査を依頼します。"
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client):
        agent = SupervisorAgent()
        messages = [MagicMock(content="動画企画について相談")]
        res = agent.route(messages)
        
        assert res.next == "Analyst"
        assert res.reason == "初期段階なので競合調査を依頼します。"
        mock_client.models.generate_content.assert_called_once()

def test_route_api_error_fallback():
    """異常系: API呼び出しで APIError が発生した場合、FINISH にフォールバックしロギングされること"""
    mock_client = MagicMock()
    # APIErrorの引数をシンプルにするか、Exceptionのラッパーにする
    mock_client.models.generate_content.side_effect = APIError(429, {"error": "Quota exceeded"})

    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client),          patch("agents._deprecated.supervisor.logger") as mock_logger:
        agent = SupervisorAgent()
        messages = [MagicMock(content="動画企画について相談")]
        res = agent.route(messages)
        
        assert res.next == "FINISH"
        assert "API error" in res.reason
        mock_logger.error.assert_called_once()

def test_route_json_decode_error():
    """異常系: APIの戻り値がJSONとして不正な場合、JSONDecodeError をキャッチしてフォールバックすること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid_json_format"
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client),          patch("agents._deprecated.supervisor.logger") as mock_logger:
        agent = SupervisorAgent()
        messages = [MagicMock(content="動画企画について相談")]
        res = agent.route(messages)
        
        assert res.next == "FINISH"
        assert "Invalid response format" in res.reason
        mock_logger.error.assert_called_once()

def test_route_unexpected_exception():
    """異常系: API呼び出しで想定外の例外が発生した場合、フォールバックすること"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("Something went wrong")

    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=mock_client),          patch("agents._deprecated.supervisor.logger") as mock_logger:
        agent = SupervisorAgent()
        messages = [MagicMock(content="動画企画について相談")]
        res = agent.route(messages)
        
        assert res.next == "FINISH"
        assert "System error" in res.reason
        mock_logger.error.assert_called_once()

def test_route_client_not_initialized():
    """異常系: クライアントが None の場合、APIを呼び出さずにフォールバックすること"""
    with patch("agents._deprecated.supervisor.get_gemini_client", return_value=None),          patch("agents._deprecated.supervisor.logger") as mock_logger:
        agent = SupervisorAgent()
        messages = [MagicMock(content="動画企画について相談")]
        res = agent.route(messages)
        
        assert res.next == "FINISH"
        assert "Client initialization failed" in res.reason
        mock_logger.error.assert_called_once()

def test_get_model_fallback_on_import_error():
    """model_registry のインポートエラー時、フォールバックの get_model が gemini-2.0-flash を返すこと"""
    original_model_registry = sys.modules.get("model_registry")
    if "model_registry" in sys.modules:
        del sys.modules["model_registry"]
        
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if name == "model_registry":
            raise ImportError("mock import error")
        return original_import(name, *args, **kwargs)

    try:
        with patch("builtins.__import__", side_effect=mock_import):
            # _deprecated.supervisor モジュールをアンロードして再インポートさせる
            for k in list(sys.modules.keys()):
                if "supervisor" in k:
                    del sys.modules[k]
            
            import agents._deprecated.supervisor as sup_mod
            assert sup_mod.get_model("any") == "gemini-2.0-flash"
    finally:
        if original_model_registry:
            sys.modules["model_registry"] = original_model_registry
