import sys
import os
import pytest
from unittest.mock import patch, MagicMock, mock_open

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.agent_base import Agent, DummyClient

# Concrete implementation of Agent for testing
class MockAgent(Agent):
    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        return self._create_base_response()

@pytest.fixture(autouse=True)
def mock_agent_soul():
    with patch("agents.agent_base.Agent._load_soul", return_value={
        "stats": {"debates": 0, "wins": 0, "losses": 0},
        "bias_weight": 1.0,
        "history": []
    }), patch("agents.agent_base.Agent._save_soul"):
        yield

def test_dummy_client_fallback():
    """get_gemini_client()がNoneを返す場合、DummyClientが設定され、API呼び出しでRuntimeErrorが発生することを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert isinstance(agent.client, DummyClient)
        
        with pytest.raises(RuntimeError) as excinfo:
            agent.client.models.generate_content(model="gemini-2.5-flash", contents="test")
        assert "Gemini Client is not initialized (API Key missing)" in str(excinfo.value)

def test_create_base_response_contains_defaults():
    """_create_base_responseがデフォルトのキーと値を含んでいることを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        res = agent.process({}, {})
        
        assert res["agent"] == "TestAgent"
        assert res["role"] == "Tester"
        assert res["color"] == "#123456"
        assert "timestamp" in res
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "No opinion"
        assert res["detail"] == ""


def test_load_soul_json_decode_error():
    """_load_soulでJSONDecodeErrorが発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None),          patch("builtins.open", mock_open(read_data="invalid json")),          patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0
        assert agent.soul["bias_weight"] == 1.0

def test_load_soul_os_error():
    """_load_soulでOSErrorが発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = OSError("Permission denied")
    with patch("agents.agent_base.get_gemini_client", return_value=None),          patch("builtins.open", return_value=mock_file),          patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_load_soul_unexpected_exception():
    """_load_soulで予期せぬ例外(Exception)が発生した際、クラッシュせずにデフォルトのsoulを返すことを確認"""
    mock_file = MagicMock()
    mock_file.__enter__.side_effect = Exception("Unexpected memory failure")
    with patch("agents.agent_base.get_gemini_client", return_value=None),          patch("builtins.open", return_value=mock_file),          patch("os.path.exists", return_value=True):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        assert agent.soul["stats"]["debates"] == 0

def test_save_soul_unexpected_exception():
    """_save_soulで予期せぬ例外(Exception)が発生した際、エラーがキャッチされクラッシュしないことを確認"""
    with patch("agents.agent_base.get_gemini_client", return_value=None),          patch("builtins.open", side_effect=Exception("Disk failure")):
        agent = MockAgent("TestAgent", "Tester", "#123456")
        # _save_soulが呼び出されてもクラッシュしない
        agent._save_soul()
