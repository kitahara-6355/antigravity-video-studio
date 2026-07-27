import pytest
import sys
import os
import json
import tempfile
import importlib
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import agents.agent_base as agent_base
from agents.agent_base import Agent

class TestAgentBaseCoverage:

    def test_import_error_fallback(self):
        # model_registry がインポートできない場合のフォールバックの検証
        original_model_registry = sys.modules.get("model_registry", None)
        
        # sys.modulesから一時的に除外
        sys.modules["model_registry"] = None
        try:
            importlib.reload(agent_base)
            # get_model関数を呼び出し、デフォルトの "gemini-2.5-flash" が返ることを確認
            assert agent_base.get_model("test") == "gemini-2.5-flash"
        finally:
            if original_model_registry is not None:
                sys.modules["model_registry"] = original_model_registry
            else:
                del sys.modules["model_registry"]
            importlib.reload(agent_base)

    def test_dir_creation_if_not_exists(self):
        # memory_dirが存在しない場合に自動作成されることを検証
        with tempfile.TemporaryDirectory() as tmpdir:
            # os.path.dirname をパッチして一時ディレクトリ配下に memory フォルダが作られるようにする
            with patch("agents.agent_base.get_gemini_client"),                  patch("agents.agent_base.get_model", return_value="gemini-mock"),                  patch("agents.agent_base.os.path.dirname", return_value=tmpdir):
                
                class DummyAgent(Agent):
                    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                        return {}
                
                agent = DummyAgent("test_agent", "tester")
                expected_dir = os.path.join(tmpdir, "memory")
                # ディレクトリが作成されていることの検証
                assert os.path.exists(expected_dir)

    def test_load_soul_exception_fallback(self):
        # 壊れたJSONファイルを読み込む際の例外フォールバックの検証 (TD-186)
        with tempfile.TemporaryDirectory() as tmpdir:
            soul_file = os.path.join(tmpdir, "test_agent.json")
            with open(soul_file, "w", encoding="utf-8") as f:
                f.write("{invalid json file}")
                
            class DummyAgent(Agent):
                def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                    return {}

            # get_gemini_client をモック化して実際の API コールを防止
            with patch("agents.agent_base.get_gemini_client"):
                agent = DummyAgent("test_agent", "tester")
                # soul_pathを変更して_load_soulを走らせる
                agent.soul_path = soul_file
                loaded_soul = agent._load_soul()
                
                # デフォルトの魂構造が返っていることを検証
                assert loaded_soul["bias_weight"] == 1.0
                assert "stats" in loaded_soul
                assert loaded_soul["stats"]["debates"] == 0

    def test_save_soul_type_error_fallback(self, capsys):
        # シリアライズ不可能なオブジェクトを保存しようとした時の例外フォールバックの検証 (TD-273)
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with patch("agents.agent_base.get_gemini_client"),              patch("agents.agent_base.Agent._save_soul", wraps=Agent._save_soul):
            agent = DummyAgent("test_agent_save_err", "tester")
            
            # TypeErrorを起こすために、setオブジェクトを仕込む
            agent.soul = {"unserializable": {1, 2, 3}}
            agent._save_soul()
            
            captured = capsys.readouterr()
            assert f"Error saving soul for {agent.name}:" in captured.out

    def test_save_soul_os_error_fallback(self, capsys):
        # ディレクトリ権限エラーなどによるOSErrorフォールバックの検証 (TD-273)
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with patch("agents.agent_base.get_gemini_client"):
            agent = DummyAgent("test_agent_os_err", "tester")
            
            # 存在しない書き込み不可能な絶対パスを指定するなどの方法でOSErrorを誘発
            agent.soul_path = "/non_existent_and_invalid_path/soul.json"
            agent._save_soul()
            
            captured = capsys.readouterr()
            assert f"Error saving soul for {agent.name}:" in captured.out

    def test_process_abstract_method_coverage(self):
        # process 抽象メソッドの pass 行をカバーする
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return super().process(input_data, context, council_context)

        with patch("agents.agent_base.get_gemini_client"):
            agent = DummyAgent("test_abstract", "tester")
            res = agent.process({}, {})
            assert res is None

    def test_inject_council_findings_coverage(self):
        # _inject_council_findings の分岐を網羅
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with patch("agents.agent_base.get_gemini_client"):
            agent = DummyAgent("my_agent", "tester")
            
            # 1. council_context is None
            assert agent._inject_council_findings(None) == ""
            
            # 2. findings が空の場合
            mock_context_empty = MagicMock()
            mock_context_empty.get_findings.return_value = {}
            assert agent._inject_council_findings(mock_context_empty) == ""
            
            # 3. findings が存在する場合
            mock_context_with_findings = MagicMock()
            mock_context_with_findings.get_findings.return_value = {
                "other_agent_1": "findings from 1",
                "my_agent": "my own findings should be ignored",
                "other_agent_2": "findings from 2"
            }
            
            findings_str = agent._inject_council_findings(mock_context_with_findings)
            assert "🏛️ 専門家メンバーからの知見" in findings_str
            assert "other_agent_1" in findings_str
            assert "findings from 1" in findings_str
            assert "other_agent_2" in findings_str
            assert "findings from 2" in findings_str
            assert "my_agent" not in findings_str


    def test_learn_approve_stance_agree(self):
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.agent_base.get_gemini_client"), \
                 patch("agents.agent_base.os.path.dirname", return_value=tmpdir):
                agent = DummyAgent("test_agent_learn_approve", "tester")
                agent.learn("session_123", "AGREE", "APPROVE")
                assert agent.soul["stats"]["debates"] == 1
                assert agent.soul["stats"]["wins"] == 1

    def test_learn_reject_stance_agree_with_feedback(self, capsys):
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.agent_base.get_gemini_client"), \
                 patch("agents.agent_base.os.path.dirname", return_value=tmpdir):
                agent = DummyAgent("test_agent_learn_reject", "tester")
                agent.learn("session_123", "AGREE", "REJECT", "poor logic")
                assert agent.soul["stats"]["debates"] == 1
                assert agent.soul["stats"]["losses"] == 1
                assert len(agent.soul["lessons"]) == 1
                assert agent.soul["bias_weight"] == 0.9
                
                captured = capsys.readouterr()
                assert "Learned Lesson:" in captured.out

    def test_recall(self):
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.agent_base.get_gemini_client"), \
                 patch("agents.agent_base.os.path.dirname", return_value=tmpdir):
                agent = DummyAgent("test_agent_recall", "tester")
                agent.soul["lessons"] = [
                    {"text": "lesson 1", "created_at": 123, "weight": 1.0}
                ]
                assert agent.recall("query") == ["lesson 1"]

    def test_create_base_response(self):
        class DummyAgent(Agent):
            def process(self, input_data: dict, context: dict, council_context=None) -> dict:
                return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.agent_base.get_gemini_client"), \
                 patch("agents.agent_base.os.path.dirname", return_value=tmpdir):
                agent = DummyAgent("test_agent_response", "tester", color="#ff0000")
                resp = agent._create_base_response()
                assert resp["agent"] == "test_agent_response"
                assert resp["role"] == "tester"
                assert resp["color"] == "#ff0000"

    def test_adk_import_error_coverage(self):
        # google.adk 関連のインポート失敗分岐 (HAS_ADK = False) を検証
        original_adk_agents = sys.modules.get("google.adk.agents", None)
        original_adk_runners = sys.modules.get("google.adk.runners", None)

        sys.modules["google.adk.agents"] = None
        sys.modules["google.adk.runners"] = None
        try:
            if "agents.agent_base" in sys.modules:
                del sys.modules["agents.agent_base"]
            import agents.agent_base as reloaded_agent_base
            assert reloaded_agent_base.HAS_ADK is False
        finally:
            if original_adk_agents is not None:
                sys.modules["google.adk.agents"] = original_adk_agents
            else:
                sys.modules.pop("google.adk.agents", None)
            if original_adk_runners is not None:
                sys.modules["google.adk.runners"] = original_adk_runners
            else:
                sys.modules.pop("google.adk.runners", None)
            sys.modules["agents.agent_base"] = agent_base
            importlib.reload(agent_base)
