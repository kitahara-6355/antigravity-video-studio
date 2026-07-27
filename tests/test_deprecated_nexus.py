import pytest
from unittest.mock import MagicMock, patch, ANY
import json
import sys
import os

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents._deprecated.nexus import Nexus

@pytest.fixture(autouse=True)
def mock_agent_soul():
    """Agent のソウル（記憶ファイル）の読み書きをモック化してディスク書き込みを防ぐ"""
    with patch("agents.agent_base.Agent._load_soul", return_value={
        "stats": {"debates": 0, "wins": 0, "losses": 0},
        "bias_weight": 1.0,
        "history": []
    }), patch("agents.agent_base.Agent._save_soul"):
        yield

def test_init_success():
    """正常初期化テスト"""
    mock_client = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"):
        
        agent = Nexus()
        assert agent.name == "Nexus"
        assert agent.role == "Router"
        assert agent.color == "#888888"
        assert agent.client == mock_client
        assert agent.model_name == "mock-nexus-model"

def test_process_success():
    """Nexus.process() の正常系テスト: APIが正しいJSONを返し、必要なエージェントが正しく抽出されること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "needed_agents": ["Analyst", "Director"],
        "reason": "市場分析と動画演出が必要です。"
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"):
        
        agent = Nexus()
        input_data = {"text": "新しい動画の企画について相談したい。視聴維持率を上げたい。"}
        context = {}
        
        res = agent.process(input_data, context)
        
        assert res["action"] == "ROUTE"
        assert res["needed_agents"] == ["Analyst", "Director"]
        assert res["synthesis"] == "市場分析と動画演出が必要です。"
        assert res["agent"] == "Nexus"
        assert res["role"] == "Router"
        assert "timestamp" in res
        
        mock_client.models.generate_content.assert_called_once()

def test_process_api_exception():
    """Nexus.process() の異常系テスト: APIが例外をスローした場合に適切にフォールバックすること"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API Failure")

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        input_data = {"text": "エラーが発生するインプット"}
        context = {}
        
        res = agent.process(input_data, context)
        
        assert res["action"] == "ROUTE"
        assert res["needed_agents"] == ["Strategist"]
        assert "ルーティング判断に失敗しました" in res["synthesis"]
        
        mock_logger.error.assert_called_once()

def test_process_invalid_json():
    """Nexus.process() の異常系テスト: APIが不正なJSONを返した場合に適切にフォールバックすること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid-json"
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        input_data = {"text": "不正なJSONを返すケース"}
        context = {}
        
        res = agent.process(input_data, context)
        
        assert res["action"] == "ROUTE"
        assert res["needed_agents"] == ["Strategist"]
        assert "ルーティング判断に失敗しました（応答形式エラー）" in res["synthesis"]
        
        mock_logger.warning.assert_called_once()

def test_synthesize_empty_responses():
    """Nexus.synthesize() のエッジケース: council_responses が空または None の場合に早期リターンすること"""
    mock_client = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=mock_client):
        agent = Nexus()
        
        # 空のリスト
        res = agent.synthesize([])
        assert res["type"] == "SYNTHESIS"
        assert "議論が十分に行われなかったため" in res["proposal"]
        assert res["options"] == ["Approve", "Reject"]
        
        # None の場合
        res_none = agent.synthesize(None)
        assert res_none["type"] == "SYNTHESIS"
        assert "議論が十分に行われなかったため" in res_none["proposal"]
        
        # APIが呼び出されていないことを確認
        mock_client.models.generate_content.assert_not_called()

def test_synthesize_success():
    """Nexus.synthesize() の正常系テスト: APIが正しいJSONを返し、統合提案が作成されること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "proposal": "統合された具体的なテスト提案",
        "summary": "テスト要約",
        "options": ["Approve", "Reject"]
    })
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"):
        
        agent = Nexus()
        council_responses = [
            {"agent": "Analyst", "synthesis": "視聴維持率は現在40%です。"},
            {"agent": "Strategist", "synthesis": "コンセプトの再定義が必要です。"}
        ]
        
        res = agent.synthesize(council_responses)
        
        assert res["type"] == "SYNTHESIS"
        assert res["proposal"] == "統合された具体的なテスト提案"
        assert res["summary"] == "テスト要約"
        assert res["options"] == ["Approve", "Reject"]
        
        mock_client.models.generate_content.assert_called_once()

def test_synthesize_api_exception():
    """Nexus.synthesize() の異常系テスト: APIが例外をスローした場合に適切にフォールバックすること"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API Synthesis Failure")

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        council_responses = [
            {"agent": "Analyst", "synthesis": "視聴維持率は現在40%です。"}
        ]
        
        res = agent.synthesize(council_responses)
        
        assert res["type"] == "SYNTHESIS"
        assert "議論の統合中にエラーが発生しましたが" in res["proposal"]
        assert res["options"] == ["Approve", "Reject"]
        mock_logger.error.assert_called_once()

def test_synthesize_invalid_json():
    """Nexus.synthesize() の異常系テスト: APIが不正なJSONを返した場合に適切にフォールバックすること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid-json"
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        council_responses = [
            {"agent": "Analyst", "synthesis": "視聴維持率は現在40%です。"}
        ]
        
        res = agent.synthesize(council_responses)
        
        assert res["type"] == "SYNTHESIS"
        assert "議論の統合中に形式エラーが発生しましたが" in res["proposal"]
        assert res["options"] == ["Approve", "Reject"]
        mock_logger.warning.assert_called_once()


def test_process_missing_keys():
    """Nexus.process() の正常系テスト: APIが空のJSONを返した場合にデフォルト値が適用されること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({})
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"):
        
        agent = Nexus()
        input_data = {"text": "テスト"}
        context = {}
        
        res = agent.process(input_data, context)
        
        assert res["action"] == "ROUTE"
        assert res["needed_agents"] == []
        assert res["synthesis"] == "意図に基づいて専門家をアサインしました。"


def test_process_json_decode_error_with_none_response():
    """Nexus.process() の異常系テスト: responseがNoneの状態でJSONDecodeErrorが発生した場合の挙動"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = json.JSONDecodeError("Expecting value", "", 0)

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        input_data = {"text": "テスト"}
        context = {}
        
        res = agent.process(input_data, context)
        
        assert res["action"] == "ROUTE"
        assert res["needed_agents"] == ["Strategist"]
        assert "ルーティング判断に失敗しました（応答形式エラー）" in res["synthesis"]
        
        mock_logger.warning.assert_called_once()
        log_msg = mock_logger.warning.call_args[0][0]
        assert "response.text: None" in log_msg


def test_synthesize_missing_keys():
    """Nexus.synthesize() のテスト: APIが空のJSONを返した場合にデフォルト提案と空のサマリーが適用されること"""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({})
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"):
        
        agent = Nexus()
        council_responses = [{"agent": "Analyst", "synthesis": "テスト"}]
        
        res = agent.synthesize(council_responses)
        
        assert res["type"] == "SYNTHESIS"
        assert res["proposal"] == "議論を統合した結果、現在の戦略を継続することを提案します。"
        assert res["summary"] == ""
        assert res["options"] == ["Approve", "Reject"]


def test_synthesize_json_decode_error_with_none_response():
    """Nexus.synthesize() の異常系テスト: responseがNoneの状態でJSONDecodeErrorが発生した場合の挙動"""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = json.JSONDecodeError("Expecting value", "", 0)

    with patch("agents.agent_base.get_gemini_client", return_value=mock_client), \
         patch("agents.agent_base.get_model", return_value="mock-nexus-model"), \
         patch("agents._deprecated.nexus.logger") as mock_logger:
        
        agent = Nexus()
        council_responses = [{"agent": "Analyst", "synthesis": "テスト"}]
        
        res = agent.synthesize(council_responses)
        
        assert res["type"] == "SYNTHESIS"
        assert "議論の統合中に形式エラーが発生しましたが" in res["proposal"]
        assert res["options"] == ["Approve", "Reject"]
        
        mock_logger.warning.assert_called_once()
        log_msg = mock_logger.warning.call_args[0][0]
        assert "response.text: None" in log_msg

