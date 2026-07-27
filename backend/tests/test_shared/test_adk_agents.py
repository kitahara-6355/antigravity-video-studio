import pytest
import sys
import json
import os
import importlib
from unittest.mock import MagicMock, patch

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# モック用 Event クラス定義
class MockPart:
    def __init__(self, text):
        self.text = text

class MockContent:
    def __init__(self, text):
        self.parts = [MockPart(text)]

class MockEvent:
    def __init__(self, text):
        self.content = MockContent(text)

    def is_final_response(self):
        return True

# テストクラス
class TestADKAgents:

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # 魂メモリがテスト実行ごとに disk に保存されて汚染されないように、_save_soul をモック化する
        self.patcher_save_soul = patch("agents.agent_base.Agent._save_soul")
        self.mock_save_soul = self.patcher_save_soul.start()
        yield
        self.patcher_save_soul.stop()

    def test_import_error_coverage(self):
        # agent_base.py の ImportError 分岐を網羅するための reload テスト
        import sys
        import importlib
        
        # google.adk 関連のモジュールを一時的に sys.modules から退避させてインポート不能にする
        original_modules = {}
        for key in list(sys.modules.keys()):
            if "google.adk" in key or "google.adk.agents" in key or "google.adk.runners" in key:
                original_modules[key] = sys.modules[key]
                sys.modules[key] = None
        
        try:
            import agents.agent_base as agent_base
            importlib.reload(agent_base)
            assert agent_base.HAS_ADK is False
        finally:
            # 元の状態に戻す
            for key, val in original_modules.items():
                if val is None:
                    if key in sys.modules:
                        del sys.modules[key]
                else:
                    sys.modules[key] = val
            import agents.agent_base as agent_base
            importlib.reload(agent_base)

    def test_has_adk_true_strategist_success(self):
        # Strategist が ADK 経由で正常にレスポンスを返すテスト
        from agents.strategist import Strategist
        
        mock_response_json = {
            "stance": "AGREE",
            "summary": "完璧な適合",
            "detail": "ブランドターゲットとトーンに完全に合致しています。",
            "glossary": []
        }
        
        mock_runner = MagicMock()
        mock_runner.run.return_value = [MockEvent(json.dumps(mock_response_json, ensure_ascii=False))]
        
        with patch("agents.agent_base.HAS_ADK", True), \
             patch("agents.strategist.HAS_ADK", True), \
             patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
             
            agent = Strategist()
            res = agent.process({"text": "動画編集のAIツール紹介", "mode": "pre_production"}, {})
            
            assert res["stance"] == "AGREE"
            assert res["summary"] == "完璧な適合"
            assert mock_runner.auto_create_session is True

    def test_has_adk_true_director_success(self):
        # Director が ADK 経由で正常にレスポンスを返すテスト
        from agents.director import Director
        
        mock_response_json = {
            "stance": "NEUTRAL",
            "summary": "テンポは良好",
            "detail": "構成案は良いですが、カットの間隔を少し調整することを推奨します。",
            "glossary": []
        }
        
        mock_runner = MagicMock()
        mock_runner.run.return_value = [MockEvent(json.dumps(mock_response_json, ensure_ascii=False))]
        
        with patch("agents.agent_base.HAS_ADK", True), \
             patch("agents.director.HAS_ADK", True), \
             patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
             
            agent = Director()
            res = agent.process({"text": "トランジションの追加", "mode": "post_production"}, {})
            
            assert res["stance"] == "NEUTRAL"
            assert res["summary"] == "テンポは良好"
            assert mock_runner.auto_create_session is True

    def test_has_adk_true_analyst_success(self):
        # Analyst が ADK 経由で正常にレスポンスを返すテスト
        from agents.analyst import Analyst
        
        mock_runner = MagicMock()
        
        # モックのADK出力（JSON markdown ブロックを模擬）
        mock_adk_output = "```json\n{\"stance\": \"AGREE\", \"summary\": \"予測CTR: 6.2%\", \"detail\": \"良好な予測値です。\", \"data\": {\"predicted_ctr\": 6.2}}\n```"
        mock_runner.run.return_value = [MockEvent(mock_adk_output)]
        
        with patch("agents.agent_base.HAS_ADK", True), \
             patch("agents.analyst.HAS_ADK", True), \
             patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
             
            agent = Analyst()
            res = agent.process({"text": "AI coding tools tutorial", "mode": "pre_production"}, {})
            
            assert res["stance"] == "AGREE"
            assert "6.2" in res["summary"]
            assert mock_runner.auto_create_session is True

    def test_has_adk_true_analyst_non_dict_fallback(self):
        # Analyst ADKが辞書以外のJSON（例えばリスト）を返した場合のフォールバック動作
        from agents.analyst import Analyst
        
        mock_runner = MagicMock()
        mock_runner.run.return_value = [MockEvent("[\"item1\", \"item2\"]")]
        
        with patch("agents.agent_base.HAS_ADK", True), \
             patch("agents.analyst.HAS_ADK", True), \
             patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
             
            agent = Analyst()
            res = agent.process({"text": "AI coding tools tutorial", "mode": "pre_production"}, {})
            assert "予測CTR" in res["summary"]

    def test_has_adk_true_analyst_exception_fallback(self):
        # Analyst 内で ADK 実行時にパースエラーが発生した場合のフォールバックテスト
        from agents.analyst import Analyst
        
        mock_runner = MagicMock()
        mock_runner.run.return_value = [MockEvent("invalid-json-response")]
        
        with patch("agents.agent_base.HAS_ADK", True), \
             patch("agents.analyst.HAS_ADK", True), \
             patch("google.adk.runners.InMemoryRunner", return_value=mock_runner):
             
            agent = Analyst()
            res = agent.process({"text": "AI coding tools tutorial", "mode": "pre_production"}, {})
            
            assert res["stance"] in ["AGREE", "DISAGREE", "NEUTRAL"]
            assert "予測CTR" in res["summary"]

    def test_has_adk_false_strategist_fallback(self):
        # HAS_ADK=False 時の Strategist フォールバックテスト (従来の generate_content)
        from agents.strategist import Strategist
        
        mock_response_json = {
            "stance": "DISAGREE",
            "summary": "ポリシー違反",
            "detail": "ブランド憲法のコンテンツポリシーに抵触しています。",
            "glossary": []
        }
        
        mock_response = MagicMock()
        mock_response.text = f"```json\n{json.dumps(mock_response_json)}\n```"
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.strategist.HAS_ADK", False):
             
            agent = Strategist()
            agent.client = mock_client
            res = agent.process({"text": "禁止コンテンツ案", "mode": "pre_production"}, {})
            
            assert res["stance"] == "DISAGREE"
            assert res["summary"] == "ポリシー違反"
            mock_client.models.generate_content.assert_called_once()

    def test_has_adk_false_director_fallback(self):
        # HAS_ADK=False 時の Director フォールバックテスト (従来の generate_content)
        from agents.director import Director
        
        mock_response_json = {
            "stance": "AGREE",
            "summary": "演出効果抜群",
            "detail": "この演出は視聴者維持率を高める可能性が高いです。",
            "glossary": []
        }
        
        mock_response = MagicMock()
        mock_response.text = f"```\n{json.dumps(mock_response_json)}\n```"
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
             
            agent = Director()
            agent.client = mock_client
            res = agent.process({"text": "面白い効果音の挿入", "mode": "post_production"}, {})
            
            assert res["stance"] == "AGREE"
            assert res["summary"] == "演出効果抜群"
            mock_client.models.generate_content.assert_called_once()

    def test_has_adk_false_analyst_fallback(self):
        # HAS_ADK=False 時の Analyst フォールバックテスト (ルールベース)
        from agents.analyst import Analyst
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.analyst.HAS_ADK", False):
             
            agent = Analyst()
            # pre_production モードのテスト
            res_pre = agent.process({"text": "テスト動画コンセプト", "mode": "pre_production"}, {})
            assert "予測CTR" in res_pre["summary"]
            
            # post_production モードのテスト
            res_post = agent.process({"text": "", "mode": "post_production"}, {})
            assert "データ分析完了" in res_post["summary"]

    def test_soul_adaptability_integration(self):
        # エージェント魂メモリ (self.soul) の学習ライフサイクルの検証
        from agents.strategist import Strategist
        
        agent = Strategist()
        agent.soul = {
            "stats": {"debates": 0, "wins": 0, "losses": 0},
            "bias_weight": 1.0,
            "history": []
        }
        
        # learn の実行
        agent.learn(session_id="test_sess", my_stance="AGREE", final_outcome="APPROVE", feedback_text="Good Job")
        assert agent.soul["stats"]["debates"] == 1
        assert agent.soul["stats"]["wins"] == 1
        
        # REJECT の場合の学習検証
        agent.learn(session_id="test_sess", my_stance="AGREE", final_outcome="REJECT", feedback_text="Off-brand visual style")
        assert agent.soul["stats"]["debates"] == 2
        assert agent.soul["stats"]["losses"] == 1
        assert agent.soul["bias_weight"] < 1.0
        assert len(agent.recall("visual style")) > 0

    def test_strategist_exception_fallback(self):
        # Strategist 内で例外が発生した場合のフォールバック動作
        from agents.strategist import Strategist
        
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API connection failed")
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.strategist.HAS_ADK", False):
             
            agent = Strategist()
            agent.client = mock_client
            res = agent.process({"text": "エラー誘発クエリ"}, {})
            
            assert res["stance"] == "NEUTRAL"
            assert "Failed to consult the Strategist" in res["detail"]

    def test_director_exception_fallback(self):
        # Director 内で例外が発生した場合のフォールバック動作
        from agents.director import Director
        
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Quota exceeded")
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
             
            agent = Director()
            agent.client = mock_client
            res = agent.process({"text": "エラー誘発クエリ"}, {})
            
            assert res["stance"] == "NEUTRAL"
            assert "Failed to consult the Director" in res["detail"]

    def test_strategist_response_list_and_non_dict_fallback(self):
        # Strategist 応答がリスト形式 JSON、および辞書以外の値のフォールバック検証
        from agents.strategist import Strategist
        
        # リスト形式 JSON
        mock_response_list = [{"stance": "NEUTRAL", "summary": "リスト形式", "detail": "リスト応答テスト", "glossary": []}]
        mock_response1 = MagicMock()
        mock_response1.text = json.dumps(mock_response_list)
        
        # 辞書以外のJSON（文字列単体など）
        mock_response2 = MagicMock()
        mock_response2.text = json.dumps("just string response")
        
        mock_client = MagicMock()
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.strategist.HAS_ADK", False):
             
            agent = Strategist()
            agent.client = mock_client
            
            # リスト形式のテスト
            mock_client.models.generate_content.return_value = mock_response1
            res1 = agent.process({"text": "テストクエリ"}, {})
            assert res1["stance"] == "NEUTRAL"
            assert res1["summary"] == "リスト形式"
            
            # 辞書以外のテスト（エラーハンドリングに突入）
            mock_client.models.generate_content.return_value = mock_response2
            res2 = agent.process({"text": "テストクエリ"}, {})
            assert res2["stance"] == "NEUTRAL"
            assert "Failed to consult the Strategist" in res2["detail"]

    def test_has_adk_false_director_pre_production(self):
        # mode == "pre_production" の分岐（31行目）をカバー
        from agents.director import Director
        
        mock_response_json = {
            "stance": "AGREE",
            "summary": "企画段階 of 演出提案",
            "detail": "サムネイルを含めた企画案は極めて有効です。",
            "glossary": []
        }
        mock_response = MagicMock()
        mock_response.text = json.dumps(mock_response_json)
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
            agent = Director()
            agent.client = mock_client
            
            res = agent.process({"text": "動画 of サムネイル企画", "mode": "pre_production"}, {})
            
            assert res["stance"] == "AGREE"
            assert res["summary"] == "企画段階 of 演出提案"
            # generate_content of 呼び出し時の system_instruction に PRE-PRODUCTION が含まれていること
            call_args = mock_client.models.generate_content.call_args[1]
            assert "PRE-PRODUCTION" in call_args["config"].system_instruction

    def test_has_adk_false_director_json_markdown_block(self):
        # ```json マークダウン除去処理（122行目）をカバー
        from agents.director import Director
        
        mock_response = MagicMock()
        mock_response.text = "```json\n{\"stance\": \"AGREE\", \"summary\": \"JSONブロック形式\"}\n```"
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
            agent = Director()
            agent.client = mock_client
            
            res = agent.process({"text": "テストクエリ"}, {})
            assert res["stance"] == "AGREE"
            assert res["summary"] == "JSONブロック形式"

    def test_has_adk_false_director_list_response(self):
        # 応答結果がリスト形式 `[dict]` で返された場合に、リスト of 先頭要素を抽出する処理（129行目）をカバー
        from agents.director import Director
        
        mock_response = MagicMock()
        mock_response.text = "[{\"stance\": \"NEUTRAL\", \"summary\": \"リスト内オブジェクト\"}]"
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
            agent = Director()
            agent.client = mock_client
            
            res = agent.process({"text": "テストクエリ"}, {})
            assert res["stance"] == "NEUTRAL"
            assert res["summary"] == "リスト内オブジェクト"

    def test_has_adk_false_director_non_dict_value_error(self):
        # パース結果が辞書型以外 of 場合 of ValueError 例外送出（132行目）をカバー
        from agents.director import Director
        
        mock_response = MagicMock()
        mock_response.text = "\"plain string response\""
        
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
            agent = Director()
            agent.client = mock_client
            
            res = agent.process({"text": "テストクエリ"}, {})
            assert res["stance"] == "NEUTRAL"
            assert "Failed to consult the Director" in res["detail"]

    def test_has_adk_false_director_http_exception_propagation(self):
        # HTTPException をキャッチした際に、そのまま呼び出し元へ raise する処理（139行目）をカバー
        from agents.director import Director
        from fastapi import HTTPException
        
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = HTTPException(status_code=400, detail="Propagated error")
        
        with patch("agents.agent_base.HAS_ADK", False), \
             patch("agents.director.HAS_ADK", False):
            agent = Director()
            agent.client = mock_client
            
            with pytest.raises(HTTPException) as exc_info:
                agent.process({"text": "テストクエリ"}, {})
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail == "Propagated error"
