import sys
import os
import pytest
import json
from unittest.mock import MagicMock, patch

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.analyst import Analyst

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
    analyst = Analyst()
    assert analyst.name == "Analyst"
    assert analyst.role == "Data Scientist"
    assert analyst.color == "#F59E0B"

def test_process_pre_production_neutral():
    """pre_production モード: CTRが中程度 (4.0 <= CTR < 5.0) の場合のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "中程度のCTRのタイトル案"}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.5), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert "4.5%" in res["summary"]
        assert "A/Bテストを実施することを推奨" in res["detail"]
        assert res["data"]["predicted_ctr"] == 4.5

def test_process_pre_production_agree():
    """pre_production モード: CTRが高い (>= 5.0) の場合のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "高いCTRのタイトル案"}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.5), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "5.5%" in res["summary"]
        assert "強く推奨します" in res["detail"]
        assert res["data"]["predicted_ctr"] == 5.5

def test_process_pre_production_disagree():
    """pre_production モード: CTRが低い (< 4.0) の場合のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "低いCTRのタイトル案"}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=3.5), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert "3.5%" in res["summary"]
        assert "基準値（4.0%）を下回っています" in res["detail"]
        assert res["data"]["predicted_ctr"] == 3.5

def test_process_pre_production_with_distilled_knowledge():
    """pre_production モード: 蒸留知識 (wagamama_manager) によるCTR補正のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "CTR補正テスト"}
    
    # 蒸留知識モックの作成
    mock_wagamama_module = MagicMock()
    mock_wagamama_instance = MagicMock()
    mock_wagamama_instance.ledger_data = {
        "knowledge_base": [
            {"confidence": 0.9},
            {"confidence": 0.9},
            {"confidence": 0.9},
            {"confidence": 0.9},
            {"confidence": 0.9}
        ]
    }
    mock_wagamama_module.wagamama_manager = mock_wagamama_instance
    
    # sys.modules に wagamama_manager をモック登録
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.0), \
         patch("agents.analyst.HAS_ADK", False):
         
        import sys
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            res = analyst.process(input_data, {})
            # 4.0 + 0.5 = 4.5% になるはず
            assert res["data"]["predicted_ctr"] == 4.5
        finally:
            if "wagamama_manager" in sys.modules:
                del sys.modules["wagamama_manager"]

def test_process_pre_production_wagamama_import_error():
    """pre_production モード: wagamama_manager のインポートでエラーが発生しても処理が継続されることのテスト (TD-187 の検証)"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "エラー処理テスト"}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.0), \
         patch("agents.analyst.HAS_ADK", False):
         
        import sys
        sys.modules["wagamama_manager"] = None
        try:
            res = analyst.process(input_data, {})
            assert res["data"]["predicted_ctr"] == 4.0
        finally:
            if "wagamama_manager" in sys.modules:
                del sys.modules["wagamama_manager"]

def test_process_post_production_disagree():
    """post_production モード: ライバルに登録者数で負けているケース"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_my_stats = {"subscribers": 1000}
    mock_rivals = {
        "nemesis": {
            "name": "宿敵ライバル",
            "subs": 1500
        }
    }
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = mock_my_stats
    mock_analytics.scout_rivals.return_value = mock_rivals
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert "500 人差" in res["detail"]
        assert "データ分析完了" in res["summary"]

def test_process_post_production_agree():
    """post_production モード: ライバルをリードしているケース"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_my_stats = {"subscribers": 2000}
    mock_rivals = {
        "nemesis": {
            "name": "宿敵ライバル",
            "subs": 1500
        }
    }
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = mock_my_stats
    mock_analytics.scout_rivals.return_value = mock_rivals
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "リードしています" in res["detail"]

def test_process_post_production_no_nemesis():
    """post_production モード: ライバルがいないケース"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_my_stats = {"subscribers": 1000}
    mock_rivals = {} # nemesisなし
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = mock_my_stats
    mock_analytics.scout_rivals.return_value = mock_rivals
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "比較対象となるライバルが見つかりません" in res["detail"]

def test_run_adk_bridge_success():
    """HAS_ADK が True の場合で、ADK が正常に応答を返すケース"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADKテスト"}
    
    # ADKモック
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    # LLMが返すレスポンス
    mock_adk_response = {
        "stance": "AGREE",
        "summary": "ADKによる予測",
        "detail": "ADK経由での詳細アドバイス",
        "data": {"predicted_ctr": 6.0}
    }
    
    mock_part = MagicMock()
    mock_part.text = "```json\n" + json.dumps(mock_adk_response) + "\n```"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent") as mock_adk_agent, \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "ADKによる予測"
        assert res["detail"] == "ADK経由での詳細アドバイス"
        assert res["data"]["predicted_ctr"] == 6.0

def test_run_adk_bridge_invalid_json():
    """HAS_ADK が True の場合で、LLMが不正なJSONを返すケース（元の結果にフォールバックすること）"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADK不正JSONテスト"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_part = MagicMock()
    mock_part.text = "不正なテキストレスポンス"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        # 元のstanceであるAGREEになるはず
        assert res["stance"] == "AGREE"
        assert "5.0%" in res["summary"]

def test_run_adk_bridge_exception():
    """HAS_ADK が True の場合で、処理中に例外が発生するケース（元の結果にフォールバックすること）"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADK例外テスト"}
    
    mock_runner = MagicMock()
    mock_runner.run.side_effect = Exception("ADK internal error")
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        # 元の結果にフォールバックする
        assert res["stance"] == "AGREE"
        assert "5.0%" in res["summary"]

def test_run_adk_bridge_success_markdown_without_json():
    """HAS_ADK が True の場合で、ADK が ```json ではなく ``` で囲まれたJSONを返すケース"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADKテスト"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_adk_response = {
        "stance": "AGREE",
        "summary": "ADKによる予測",
        "detail": "ADK経由での詳細アドバイス",
        "data": {"predicted_ctr": 6.0}
    }
    
    mock_part = MagicMock()
    mock_part.text = "```\n" + json.dumps(mock_adk_response) + "\n```"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "ADKによる予測"
        assert res["data"]["predicted_ctr"] == 6.0


def test_run_adk_bridge_event_filtering():
    """HAS_ADK が True の場合で、is_final_response() や content, part.text が空の場合のフィルタリングをテスト (145->139, 147->146)"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADKフィルタテスト"}
    
    # イベント1: 最終レスポンスではない
    mock_event1 = MagicMock()
    mock_event1.is_final_response.return_value = False
    
    # イベント2: 最終レスポンスだが content が None
    mock_event2 = MagicMock()
    mock_event2.is_final_response.return_value = True
    mock_event2.content = None
    
    # イベント3: 最終レスポンスで content もあるが、part.text が空または None
    mock_event3 = MagicMock()
    mock_event3.is_final_response.return_value = True
    mock_part3_none = MagicMock()
    mock_part3_none.text = None
    mock_part3_empty = MagicMock()
    mock_part3_empty.text = ""
    mock_event3.content.parts = [mock_part3_none, mock_part3_empty]
    
    # イベント4: 正常なイベント
    mock_event4 = MagicMock()
    mock_event4.is_final_response.return_value = True
    mock_adk_response = {
        "stance": "AGREE",
        "summary": "ADKによるフィルタ予測",
        "detail": "ADK詳細アドバイス",
        "data": {"predicted_ctr": 6.5}
    }
    mock_part4 = MagicMock()
    mock_part4.text = json.dumps(mock_adk_response)
    mock_event4.content.parts = [mock_part4]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event1, mock_event2, mock_event3, mock_event4]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "ADKによるフィルタ予測"
        assert res["data"]["predicted_ctr"] == 6.5


def test_run_adk_bridge_non_dict_result():
    """ADK の返却結果が辞書形式ではない場合 (157->164)"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADK非辞書テスト"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    # リスト形式のJSON
    mock_part = MagicMock()
    mock_part.text = "[1, 2, 3]"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        # isinstance(adk_result, dict) が False なので、元の結果 (予測CTR: 5.0%) が返る
        assert res["stance"] == "AGREE"
        assert "5.0%" in res["summary"]


def test_process_pre_production_wagamama_other_exceptions():
    """wagamama_manager で AttributeError, KeyError, TypeError が発生した場合のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "エラー処理テスト"}
    
    class DummyWagamamaAttrErr:
        @property
        def ledger_data(self):
            raise AttributeError("no attribute")

    class DummyWagamamaKeyErr:
        @property
        def ledger_data(self):
            raise KeyError("no key")

    class DummyWagamamaTypeErr:
        @property
        def ledger_data(self):
            raise TypeError("type error")
            
    class DummyModule:
        def __init__(self, manager):
            self.wagamama_manager = manager

    for dummy_manager in [DummyWagamamaAttrErr(), DummyWagamamaKeyErr(), DummyWagamamaTypeErr()]:
        with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.0), \
             patch("agents.analyst.HAS_ADK", False):
             
            import sys
            sys.modules["wagamama_manager"] = DummyModule(dummy_manager)
            try:
                res = analyst.process(input_data, {})
                # エラーがキャッチされて 4.0% のまま継続するはず
                assert res["data"]["predicted_ctr"] == 4.0
            except Exception as e:
                pytest.fail(f"Unexpected exception raised: {e}")
            finally:
                if "wagamama_manager" in sys.modules:
                    del sys.modules["wagamama_manager"]


def test_process_pre_production_wagamama_less_than_five_items():
    """pre_production モード: 蒸留知識が5件未満（例：3件）の場合の補正処理のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "CTR補正テスト（件数少）"}
    
    mock_wagamama_module = MagicMock()
    mock_wagamama_instance = MagicMock()
    mock_wagamama_instance.ledger_data = {
        "knowledge_base": [
            {"confidence": 0.8},
            {"confidence": 0.8},
            {"confidence": 0.8}
        ]
    }
    mock_wagamama_module.wagamama_manager = mock_wagamama_instance
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.0),          patch("agents.analyst.HAS_ADK", False):
         
        import sys
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            res = analyst.process(input_data, {})
            assert res["data"]["predicted_ctr"] == 4.3
        finally:
            if "wagamama_manager" in sys.modules:
                del sys.modules["wagamama_manager"]


def test_process_pre_production_wagamama_missing_confidence():
    """pre_production モード: 蒸留知識内のデータに confidence キーが欠落している場合のデフォルト値（0.9）適用のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "CTR補正テスト（キー欠落）"}
    
    mock_wagamama_module = MagicMock()
    mock_wagamama_instance = MagicMock()
    mock_wagamama_instance.ledger_data = {
        "knowledge_base": [
            {}
        ]
    }
    mock_wagamama_module.wagamama_manager = mock_wagamama_instance
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.0),          patch("agents.analyst.HAS_ADK", False):
         
        import sys
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            res = analyst.process(input_data, {})
            assert res["data"]["predicted_ctr"] == 4.5
        finally:
            if "wagamama_manager" in sys.modules:
                del sys.modules["wagamama_manager"]


def test_process_pre_production_ctr_upper_limit():
    """pre_production モード: 補正後の予測CTRが上限（15.0%）を超える場合のクリッピング処理のテスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "CTR上限テスト"}
    
    mock_wagamama_module = MagicMock()
    mock_wagamama_instance = MagicMock()
    mock_wagamama_instance.ledger_data = {
        "knowledge_base": [
            {"confidence": 1.0}
        ]
    }
    mock_wagamama_module.wagamama_manager = mock_wagamama_instance
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=14.8),          patch("agents.analyst.HAS_ADK", False):
         
        import sys
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            res = analyst.process(input_data, {})
            assert res["data"]["predicted_ctr"] == 15.0
        finally:
            if "wagamama_manager" in sys.modules:
                del sys.modules["wagamama_manager"]


def test_process_pre_production_missing_text():
    """pre_production モード: 入力データに text キーが欠落している場合のエッジケース of テスト"""
    analyst = Analyst()
    input_data = {"mode": "pre_production"}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=4.2),          patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["data"]["predicted_ctr"] == 4.2
        assert "タイトル案「...」" in res["detail"]


def test_init_model_from_registry():
    """Model Registryから適切なモデル（analyst）を取得することの検証"""
    with patch("model_registry.get_model", return_value="gemini-test-analyst-model") as mock_get_model:
        analyst = Analyst()
        assert analyst.model_name == "gemini-test-analyst-model"
        mock_get_model.assert_called_with("analyst")


def test_process_pre_production_query_none():
    """pre_production モード: 入力データ text が None の場合のエッジケース検証"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": None}
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=3.0) as mock_calc, \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert res["data"]["predicted_ctr"] == 3.0
        mock_calc.assert_called_with("")


def test_run_adk_bridge_overwrites_prevented():
    """ADK応答に含まれる agent, role, color などが基本情報で強制上書きガードされることの検証"""
    analyst = Analyst()
    input_data = {"mode": "pre_production", "text": "ADK上書きテスト"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_adk_response = {
        "agent": "FakeAgent",
        "role": "FakeRole",
        "color": "#000000",
        "stance": "AGREE",
        "summary": "ADKによる予測",
        "detail": "ADK経由での詳細アドバイス",
        "data": {"predicted_ctr": 6.0}
    }
    
    mock_part = MagicMock()
    mock_part.text = json.dumps(mock_adk_response)
    mock_event.content.parts = [mock_part]
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("plugins.youtube_optimizer_plugin.YouTubeOptimizerPlugin.calculate_video_ctr", return_value=5.0), \
         patch("agents.analyst.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"):
         
        res = analyst.process(input_data, {})
        assert res["agent"] == "Analyst"
        assert res["role"] == "Data Scientist"
        assert res["color"] == "#F59E0B"


def test_process_post_production_no_rivals_correct_message():
    """post_production モード: nemesis (ライバル) が存在しない場合のアドバイスとスタンスをテスト"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_my_stats = {"subscribers": 1000}
    mock_rivals = {"nemesis": None, "benchmark": None}
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = mock_my_stats
    mock_analytics.scout_rivals.return_value = mock_rivals
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "比較対象となるライバルが見つかりません" in res["detail"]


def test_process_post_production_corrupted_my_stats():
    """post_production モード: my_stats が None や辞書ではない場合のエッジケースをテスト"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = None  # 不正な戻り値
    mock_analytics.scout_rivals.return_value = {}
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "比較対象となるライバルが見つかりません" in res["detail"]


def test_process_post_production_nemesis_missing_keys():
    """post_production モード: nemesis に subs や name が欠落している場合のエッジケースをテスト"""
    analyst = Analyst()
    input_data = {"mode": "post_production"}
    
    mock_my_stats = {"subscribers": 1000}
    mock_rivals = {
        "nemesis": {
            # subs や name がない
            "genre": "Tech"
        }
    }
    
    mock_analytics = MagicMock()
    mock_analytics.get_my_stats.return_value = mock_my_stats
    mock_analytics.scout_rivals.return_value = mock_rivals
    
    with patch("branding.analytics_manager.analytics_manager", mock_analytics), \
         patch("agents.analyst.HAS_ADK", False):
        res = analyst.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert "比較対象となるライバルが見つかりません" in res["detail"]
