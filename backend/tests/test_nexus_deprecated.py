import sys
import os
from unittest.mock import MagicMock
from google.genai.errors import APIError

# nexus.py をインポート
from agents._deprecated.nexus import Nexus

def test_nexus_init():
    nexus = Nexus()
    assert nexus.name == "Nexus"
    assert nexus.role == "Router"
    assert nexus.color == "#888888"

def test_nexus_process_success():
    nexus = Nexus()
    
    # client.models.generate_content をモックする
    mock_response = MagicMock()
    mock_response.text = '{"needed_agents": ["Analyst", "Director"], "reason": "分析と演出が必要です。"}'
    
    nexus.client = MagicMock()
    nexus.client.models.generate_content.return_value = mock_response
    
    input_data = {"text": "動画のパフォーマンスを改善したい"}
    context = {}
    
    res = nexus.process(input_data, context)
    
    assert res["action"] == "ROUTE"
    assert res["needed_agents"] == ["Analyst", "Director"]
    assert res["synthesis"] == "分析と演出が必要です。"
    assert res["agent"] == "Nexus"
    
    # 呼び出しパラメータの検証
    nexus.client.models.generate_content.assert_called_once()
    args, kwargs = nexus.client.models.generate_content.call_args
    assert "Analyst" in kwargs["contents"]
    assert "Strategist" in kwargs["contents"]
    assert "Director" in kwargs["contents"]
    assert kwargs["config"].response_mime_type == "application/json"

def test_nexus_process_failure():
    nexus = Nexus()
    
    # client.models.generate_content が APIError をスローするようにモックする
    nexus.client = MagicMock()
    api_err = APIError(500, {"error": "API Connection Timeout"})
    nexus.client.models.generate_content.side_effect = api_err
    
    input_data = {"text": "エラーテスト"}
    context = {}
    
    res = nexus.process(input_data, context)
    
    # フォールバック処理の検証
    assert res["action"] == "ROUTE"
    assert res["needed_agents"] == ["Strategist"]
    assert "失敗しました" in res["synthesis"]

def test_nexus_synthesize_empty():
    nexus = Nexus()
    
    # 空の議会レスポンスの場合
    res = nexus.synthesize([])
    assert res["type"] == "SYNTHESIS"
    assert "十分に行われなかったため" in res["proposal"]
    assert res["options"] == ["Approve", "Reject"]

def test_nexus_synthesize_success():
    nexus = Nexus()
    
    # client.models.generate_content をモックする
    mock_response = MagicMock()
    mock_response.text = '{"proposal": "動画構成を一部変更する提案", "summary": "構成変更", "options": ["Approve", "Reject"]}'
    
    nexus.client = MagicMock()
    nexus.client.models.generate_content.return_value = mock_response
    
    council_responses = [{"agent": "Analyst", "text": "視聴維持率を考慮すべきです。"}]
    
    res = nexus.synthesize(council_responses)
    
    assert res["type"] == "SYNTHESIS"
    assert res["proposal"] == "動画構成を一部変更する提案"
    assert res["summary"] == "構成変更"
    assert res["options"] == ["Approve", "Reject"]

def test_nexus_synthesize_failure():
    nexus = Nexus()
    
    # client.models.generate_content が APIError をスローするようにモックする
    nexus.client = MagicMock()
    api_err = APIError(500, {"error": "Synthesis Failed"})
    nexus.client.models.generate_content.side_effect = api_err
    
    council_responses = [{"agent": "Analyst", "text": "テストデータ"}]
    
    res = nexus.synthesize(council_responses)
    
    assert res["type"] == "SYNTHESIS"
    assert "エラーが発生しました" in res["proposal"]
    assert res["options"] == ["Approve", "Reject"]

def test_nexus_process_type_error():
    nexus = Nexus()
    
    # client.models.generate_content が TypeError をスローするようにモックする
    nexus.client = MagicMock()
    nexus.client.models.generate_content.side_effect = TypeError("Type mismatch")
    
    input_data = {"text": "Typeエラーテスト"}
    context = {}
    
    res = nexus.process(input_data, context)
    
    assert res["action"] == "ROUTE"
    assert res["needed_agents"] == ["Strategist"]
    assert "設定またはデータ形式のエラー" in res["synthesis"]

def test_nexus_synthesize_attribute_error():
    nexus = Nexus()
    
    # client.models.generate_content が AttributeError をスローするようにモックする
    nexus.client = MagicMock()
    nexus.client.models.generate_content.side_effect = AttributeError("Attribute missing")
    
    council_responses = [{"agent": "Analyst", "text": "テストデータ"}]
    
    res = nexus.synthesize(council_responses)
    
    assert res["type"] == "SYNTHESIS"
    assert "設定またはデータ形式のエラー" in res["proposal"]

def test_nexus_process_json_decode_error():
    nexus = Nexus()
    
    mock_response = MagicMock()
    mock_response.text = 'invalid json content'
    nexus.client = MagicMock()
    nexus.client.models.generate_content.return_value = mock_response
    
    input_data = {"text": "JSON破損テスト"}
    context = {}
    
    res = nexus.process(input_data, context)
    assert res["action"] == "ROUTE"
    assert res["needed_agents"] == ["Strategist"]
    assert "応答形式エラー" in res["synthesis"]

def test_nexus_synthesize_json_decode_error():
    nexus = Nexus()
    
    mock_response = MagicMock()
    mock_response.text = 'invalid json content'
    nexus.client = MagicMock()
    nexus.client.models.generate_content.return_value = mock_response
    
    council_responses = [{"agent": "Analyst", "text": "テストデータ"}]
    
    res = nexus.synthesize(council_responses)
    assert res["type"] == "SYNTHESIS"
    assert "形式エラーが発生しました" in res["proposal"]
