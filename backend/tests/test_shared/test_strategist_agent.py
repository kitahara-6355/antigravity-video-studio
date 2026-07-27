import pytest
import json
import sys
from unittest.mock import patch, MagicMock
from agents.strategist import Strategist
from branding_manager import branding_manager

class TestStrategistAgent:
    """
    Strategist エージェントの動作検証テスト (T-batch_d6d052-bug_hunter-002)
    """

    @patch('model_registry.get_model')
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_initialization(self, mock_get_model):
        """モデルレジストリから 'strategist' 用 of モデル名が正しく取得されて初期化されること"""
        mock_get_model.return_value = "gemini-2.5-flash-strategist"
        agent = Strategist()
        assert agent.model_name == "gemini-2.5-flash-strategist"
        mock_get_model.assert_called_with("strategist")

    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_initialization_import_error(self):
        """model_registry がインポートできない場合、フォールバックモデルが設定されること"""
        # pytest で既にロードされているため、sys.modules に None を仕込んで import エラーをシミュレート
        if 'model_registry' in sys.modules:
            orig = sys.modules['model_registry']
            sys.modules['model_registry'] = None
            try:
                # Strategist.__init__ 内で import model_registry しようとして ImportError になる
                agent = Strategist()
                assert agent.model_name == "gemini-2.5-flash"
            finally:
                sys.modules['model_registry'] = orig
        else:
            sys.modules['model_registry'] = None
            try:
                agent = Strategist()
                assert agent.model_name == "gemini-2.5-flash"
            finally:
                del sys.modules['model_registry']

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_pre_production_agree(self, mock_get_model):
        """pre_production モードで正常に応答（AGREE）が得られること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"},
            "visual_identity": {"style_prompt": "Clean and modern"},
            "content_policy": ["No clickbait"]
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        # mock client responses
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "stance": "AGREE",
            "summary": "Fits well",
            "detail": "The concept aligns perfectly with target audience.",
            "glossary": []
        })
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "AI coding tools tutorial", "mode": "pre_production"}, {})
        
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Fits well"
        assert res["detail"] == "The concept aligns perfectly with target audience."
        assert res["agent"] == "Strategist"
        assert res["role"] == "Brand Guardian"
        
        # config parameters check
        agent.client.models.generate_content.assert_called_once()
        args, kwargs = agent.client.models.generate_content.call_args
        assert kwargs["model"] == "gemini-2.5-flash"
        assert kwargs["config"].response_mime_type == "application/json"
        assert kwargs["config"].temperature == 0.3

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_post_production_disagree(self, mock_get_model):
        """post_production モードで正常に応答（DISAGREE）が得られること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"}
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "stance": "DISAGREE",
            "summary": "Too slow pacing",
            "detail": "Pacing is too slow, causing drop-offs.",
            "glossary": []
        })
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "pacing adjustments", "mode": "post_production"}, {})
        assert res["stance"] == "DISAGREE"
        assert res["summary"] == "Too slow pacing"

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_markdown_json(self, mock_get_model):
        """マークダウンデコレータ付きのJSONが返されても正しくパースして処理できること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"}
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = "```json\n{\n  \"stance\": \"NEUTRAL\",\n  \"summary\": \"Markdown JSON\",\n  \"detail\": \"Parsed successfully\",\n  \"glossary\": []\n}\n```"
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "test markdown tag"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Markdown JSON"
        assert res["detail"] == "Parsed successfully"

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_plain_markdown_code_block(self, mock_get_model):
        """```で始まり```で終わるコードブロック（json指定なし）が返されても正しくパースできること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = "```\n{\n  \"stance\": \"AGREE\",\n  \"summary\": \"Plain Markdown\",\n  \"detail\": \"OK\"\n}\n```"
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "test block"}, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Plain Markdown"

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_list_json(self, mock_get_model):
        """リスト形式のJSONが返された場合、最初の要素を取り出して辞書型として処理できること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"}
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = json.dumps([{
            "stance": "AGREE",
            "summary": "List format JSON",
            "detail": "Resolved list format to dict",
            "glossary": []
        }])
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "test list tag"}, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "List format JSON"

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_invalid_json_fallback(self, mock_get_model):
        """パース不可能な不正JSONが返された場合、システムエラーとして安全にフォールバックすること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"}
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = "Invalid JSON {{{ {--"
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "invalid json"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Parsing Error"
        assert "Failed to parse Strategist response" in res["detail"]

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_non_dict_non_list_response(self, mock_get_model):
        """AI応答が辞書型でもリスト型でもない（例: 単一の文字列）場合に、安全にフォールバックすること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        agent.client = MagicMock()
        
        mock_response = MagicMock()
        mock_response.text = "\"AGREE\""
        agent.client.models.generate_content.return_value = mock_response
        
        res = agent.process({"text": "non dict"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Parsing Error"
        assert "Failed to parse Strategist response" in res["detail"]

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_exception_fallback(self, mock_get_model):
        """API呼び出し中に例外が発生した場合、システムエラーとして安全にフォールバックすること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"}
        }
        agent = Strategist()
        agent.client = MagicMock()
        
        agent.client.models.generate_content.side_effect = RuntimeError("API error")
        
        res = agent.process({"text": "error trigger"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "API error" in res["detail"]

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', False)
    def test_strategist_process_with_lessons(self, mock_get_model):
        """過去のレッスンが存在する場合、プロンプトにレッスン内容が含まれること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        agent.client = MagicMock()
        
        with patch.object(agent, 'recall', return_value=[{"lesson": "Avoid clickbait"}]) as mock_recall:
            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "stance": "AGREE",
                "summary": "OK",
                "detail": "Adheres to lessons",
                "glossary": []
            })
            agent.client.models.generate_content.return_value = mock_response
            
            res = agent.process({"text": "test video concept"}, {})
            
            mock_recall.assert_called_once_with("test video concept")
            assert res["stance"] == "AGREE"
            args, kwargs = agent.client.models.generate_content.call_args
            assert "LEARNED LESSONS" in kwargs["config"].system_instruction

    # ----------------------------------------------------
    # ADK (HAS_ADK = True) のテストケースを追加
    # ----------------------------------------------------

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', True)
    @patch('google.adk.runners.InMemoryRunner')
    @patch('google.adk.agents.Agent')
    def test_strategist_process_adk_agree(self, mock_adk_agent, mock_runner_class, mock_get_model):
        """ADKが有効な場合に正常に応答（AGREE）が得られること"""
        branding_manager.constitution = {
            "channel_name": "TestChannel",
            "target_audience": "Tech Enthusiasts",
            "brand_personality": {"tone": "Informative"},
            "visual_identity": {"style_prompt": "Clean and modern"},
            "content_policy": ["No clickbait"]
        }
        agent = Strategist()
        
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner
        
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        
        mock_part = MagicMock()
        mock_part.text = json.dumps({
            "stance": "AGREE",
            "summary": "Fits well",
            "detail": "The concept aligns perfectly with target audience.",
            "glossary": []
        })
        mock_event.content.parts = [mock_part]
        
        mock_runner.run.return_value = [mock_event]
        
        res = agent.process({"text": "AI coding tools tutorial", "mode": "pre_production"}, {})
        
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Fits well"
        assert res["detail"] == "The concept aligns perfectly with target audience."
        
        mock_runner_class.assert_called_once()
        mock_runner.run.assert_called_once()

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', True)
    @patch('google.adk.runners.InMemoryRunner')
    @patch('google.adk.agents.Agent')
    def test_strategist_process_adk_exception(self, mock_adk_agent, mock_runner_class, mock_get_model):
        """ADK呼び出し中に例外が発生した場合、システムエラーとして安全にフォールバックすること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner
        mock_runner.run.side_effect = RuntimeError("ADK error")
        
        res = agent.process({"text": "AI coding tools tutorial"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "ADK error" in res["detail"]

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', True)
    @patch('google.adk.runners.InMemoryRunner')
    @patch('google.adk.agents.Agent')
    def test_strategist_process_adk_parse_error(self, mock_adk_agent, mock_runner_class, mock_get_model):
        """ADKからの応答が不正なJSONの場合、Parsing Errorとして捕捉されフォールバックすること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner
        
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = "invalid json"
        mock_event.content.parts = [mock_part]
        
        mock_runner.run.return_value = [mock_event]
        
        res = agent.process({"text": "AI coding tools tutorial"}, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Parsing Error"
        assert "Failed to parse Strategist response" in res["detail"]

    @patch('model_registry.get_model', return_value="gemini-2.5-flash")
    @patch('agents.strategist.HAS_ADK', True)
    @patch('google.adk.runners.InMemoryRunner')
    @patch('google.adk.agents.Agent')
    def test_strategist_process_adk_inject_council(self, mock_adk_agent, mock_runner_class, mock_get_model):
        """ADK使用時に、Councilの知見が正しくプロンプトにインジェクションされること"""
        branding_manager.constitution = {"channel_name": "Test"}
        agent = Strategist()
        
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner
        
        mock_event = MagicMock()
        mock_event.is_final_response.return_value = True
        mock_part = MagicMock()
        mock_part.text = json.dumps({
            "stance": "AGREE",
            "summary": "OK",
            "detail": "Adheres to council",
            "glossary": []
        })
        mock_event.content.parts = [mock_part]
        mock_runner.run.return_value = [mock_event]

        # CouncilContext の Mock
        mock_council_context = MagicMock()
        mock_council_context.get_findings.return_value = {
            "Analyst": "Excellent growth potential"
        }
        
        res = agent.process({"text": "AI tools"}, {}, council_context=mock_council_context)
        
        assert res["stance"] == "AGREE"
        # adk_agent のインスタンス化引数をチェック
        mock_adk_agent.assert_called_once()
        args, kwargs = mock_adk_agent.call_args
        assert "Analyst" in kwargs["instruction"]
        assert "Excellent growth potential" in kwargs["instruction"]
