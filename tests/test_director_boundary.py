import sys
import os
import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from agents.director import Director, DirectorValidationError, DirectorLLMError

@pytest.fixture(autouse=True)
def mock_agent_soul():
    """Agent のソウル（記憶ファイル）の読み書きをモック化してディスク書き込みを防ぐ"""
    with patch("agents.agent_base.Agent._load_soul", return_value={
        "stats": {"debates": 0, "wins": 0, "losses": 0},
        "bias_weight": 1.0,
        "history": []
    }), patch("agents.agent_base.Agent._save_soul"):
        yield

@pytest.fixture(autouse=True)
def mock_gemini_client():
    """get_gemini_client が常に MagicMock を返すようにパッチ"""
    mock_client = MagicMock()
    with patch("agents.agent_base.get_gemini_client", return_value=mock_client):
        yield mock_client

@pytest.fixture
def mock_branding_manager():
    """branding_manager.constitution のモック"""
    mock_bm = MagicMock()
    mock_bm.constitution = {
        "channel_name": "BoundaryTestChannel",
        "visual_identity": {"style_prompt": "BoundaryStyle"},
        "brand_personality": {"tone": "BoundaryTone"}
    }
    with patch("agents.director.branding_manager", mock_bm):
        yield mock_bm

# --- A. 入力パラメータ (input_data, context, council_context) の極端な値テスト ---

def test_process_empty_input_data(mock_branding_manager):
    """input_data が空辞書の場合、デフォルト値等でLLMが呼ばれ、正常に完了することを確認"""
    director = Director()
    input_data = {}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "NEUTRAL", "summary": "Empty input summary", "detail": "Empty detail", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Empty input summary"
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        assert kwargs.get("contents") == ""  # textが無い場合は空文字列として扱われる

def test_process_none_text_input_data(mock_branding_manager):
    """input_data の text が None の場合、空文字列として扱われて正常完了することを確認"""
    director = Director()
    input_data = {"text": None, "mode": "pre_production"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "None text summary", "detail": "None detail", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        assert kwargs.get("contents") == ""  # query は空文字列になる

def test_process_none_mode_input_data(mock_branding_manager):
    """input_data の mode が None の場合、正常動作し、デフォルトの post_production モードが適用されること"""
    director = Director()
    input_data = {"text": "Hello", "mode": None}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "NEUTRAL", "summary": "None mode summary", "detail": "None mode detail", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        sys_instr = kwargs.get("config").system_instruction
        assert "MODE: POST-PRODUCTION" in sys_instr  # デフォルトは post_production にフォールバック

def test_process_none_context(mock_branding_manager):
    """context が None の場合、process 内で {} に初期化され、エラーにならずに正常終了すること"""
    director = Director()
    input_data = {"text": "Test"}
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "Success with None context", "detail": "Detail", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, None)
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Success with None context"

def test_process_none_council_context(mock_branding_manager):
    """council_context が None の場合、連携インサイトがなくとも正常動作すること"""
    director = Director()
    input_data = {"text": "Test"}
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "Success with None council", "detail": "Detail", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {}, council_context=None)
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Success with None council"

# --- B. branding_manager 構成情報の境界値テスト ---

def test_build_system_prompt_branding_none():
    """branding_manager.constitution が None の場合でもフォールバックで正常なプロンプトが構築されること"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_bm = MagicMock()
    mock_bm.constitution = None
    
    with patch("agents.director.branding_manager", mock_bm):
        sys_prompt = director._build_system_prompt(input_data, None)
        assert "BoundaryTestChannel" not in sys_prompt
        assert "Creative Channel" in sys_prompt  # デフォルト値
        assert "Modern Creative Style" in sys_prompt  # デフォルト値
        assert "Friendly and engaging" in sys_prompt  # デフォルト値

def test_build_system_prompt_branding_invalid_type():
    """branding_manager.constitution が辞書型でない（例: 文字列）場合でもフォールバックされること"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_bm = MagicMock()
    mock_bm.constitution = "invalid_string_instead_of_dict"
    
    with patch("agents.director.branding_manager", mock_bm):
        sys_prompt = director._build_system_prompt(input_data, None)
        assert "Creative Channel" in sys_prompt

# --- C. LLMレスポンス解析 (_parse_and_validate_response) の異常系・境界値テスト ---

def test_parse_response_invalid_stance(mock_branding_manager):
    """LLMが返す stance に無効な値が含まれていた場合、NEUTRAL に正規化されること"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_response = MagicMock()
    # stance が "UNKNOWN" という無効な値
    mock_response.text = '{"stance": "UNKNOWN", "summary": "Invalid stance test", "detail": "Details", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"  # NEUTRAL にフォールバックされている
        assert res["summary"] == "Invalid stance test"

def test_parse_response_missing_keys(mock_branding_manager):
    """LLMの返答が必要なキー（summary, detailなど）を含まない最小限のJSONであってもエラーにならずベースレスポンスとマージされること"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_response = MagicMock()
    # summary や detail, glossary が欠落している最小限のJSON
    mock_response.text = '{"stance": "AGREE"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["agent"] == "Director"
        assert res["role"] == "Creative Director"
        assert "timestamp" in res
        # 欠落しているキーはデフォルトの _create_base_response から補完されないが、マージ自体は正常に行われる
        # (ただし process 内の _create_base_response() の中身は subclass からの返り値で update される)

def test_call_llm_empty_response_genai(mock_branding_manager):
    """GenAIの呼び出し結果が None あるいは空文字の場合、DirectorLLMError になりシステムエラーフォールバックされること"""
    director = Director()
    input_data = {"text": "Test"}
    
    # response.text が None のケース
    mock_response_none = MagicMock()
    mock_response_none.text = None
    
    # response.text が 空文字 のケース
    mock_response_empty = MagicMock()
    mock_response_empty.text = "   "
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director, "recall", return_value=None):
         
        # case 1: None
        with patch.object(director.client.models, "generate_content", return_value=mock_response_none):
            res = director.process(input_data, {})
            assert res["stance"] == "NEUTRAL"
            assert res["summary"] == "System Error"
            assert "returned an empty or invalid response" in res["detail"]
            
        # case 2: Empty
        with patch.object(director.client.models, "generate_content", return_value=mock_response_empty):
            res = director.process(input_data, {})
            assert res["stance"] == "NEUTRAL"
            assert res["summary"] == "System Error"
            assert "returned an empty or invalid response" in res["detail"]

def test_call_llm_empty_response_adk(mock_branding_manager):
    """ADK の呼び出し結果が空文字のみの場合、DirectorLLMError になりシステムエラーフォールバックされること"""
    director = Director()
    input_data = {"text": "ADK Empty Test"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    mock_part = MagicMock()
    mock_part.text = "   "  # 空文字レスポンス
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"),          patch("google.genai.types.Content"),          patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "ADK LLM returned an empty response" in res["detail"]

# --- D. TDR（技術負債登録）と例外安全・初期化フォールバックのテスト ---

def test_register_tdr_exception_safety(mock_branding_manager):
    """TDR登録処理自体が例外を投げた場合でも、呼び出し側に例外が伝播せず、元のエラーレスポンスが正常に返されること"""
    director = Director()
    input_data = {"text": "TDR Crash Test"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=RuntimeError("Original LLM Error")), \
         patch.object(director, "recall", return_value=None),          patch("agents.memory.technical_debt.TechnicalDebtStore", side_effect=Exception("TDR Store Crash")):
         
        # TDRがクラッシュしても、process は正常に catch し、元のエラー（Original LLM Error）をラップした System Error を返すこと
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Original LLM Error" in res["detail"]

def test_init_model_registry_fallback():
    """初期化時に model_registry からのインポートエラー等が発生した場合、デフォルトの gemini-2.5-flash にフォールバックされること"""
    with patch("model_registry.get_model", side_effect=ImportError("Mock Import Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"
        
    with patch("model_registry.get_model", side_effect=KeyError("Mock Key Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"

# --- E. ロバストな JSON 解析およびリスト内辞書探索・予期せぬ初期化例外の追加テスト ---

def test_parse_response_robust_json_extraction(mock_branding_manager):
    """LLMが余計な補足テキストや複数のJSONブロックを含んでいても、正当なJSONを抽出できることを検証"""
    director = Director()
    input_data = {"text": "Robust Test"}
    
    mock_response = MagicMock()
    # 補足テキストがあり、かつ非貪欲にマッチするJSONがあるケース
    mock_response.text = 'Some prefix text {"invalid": } and then the actual JSON: {"stance": "AGREE", "summary": "Robust Summary", "detail": "Robust Detail", "glossary": ["term1"]} and some suffix.'
    
    with patch("agents.director.HAS_ADK", False),          patch.object(director.client.models, "generate_content", return_value=mock_response),          patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Robust Summary"
        assert res["detail"] == "Robust Detail"
        assert res["glossary"] == ["term1"]

def test_parse_response_list_contains_dict(mock_branding_manager):
    """LLMがリストを返し、その中に辞書が含まれている場合、正しく辞書が抽出されることを検証"""
    director = Director()
    input_data = {"text": "List Test"}
    
    mock_response = MagicMock()
    # リストの中に辞書以外の要素と辞書があるケース
    mock_response.text = '["comment", {"stance": "DISAGREE", "summary": "Found Dict", "detail": "Details"}]'
    
    with patch("agents.director.HAS_ADK", False),          patch.object(director.client.models, "generate_content", return_value=mock_response),          patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert res["summary"] == "Found Dict"

def test_init_model_registry_unexpected_exception():
    """初期化時に model_registry からの予期せぬ例外（例: AttributeError）が発生した場合、TDRに登録しつつデフォルトにフォールバックされること"""
    # model_registry.get_model で AttributeError を発生させる
    with patch("model_registry.get_model", side_effect=AttributeError("Unexpected Attribute Error")),          patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        director = Director()
        assert director.model_name == "gemini-2.5-flash"
        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args[1]
        assert "AttributeError" in call_kwargs["notes"]
        assert "Unexpected Attribute Error" in call_kwargs["notes"]


def test_process_falsy_non_string_validation(mock_branding_manager):
    """falsyな非文字列型（Falseや0など）が渡された場合、バリデーションですり抜けず、正しく例外/Validation Errorが発生すること"""
    director = Director()
    
    # text: False
    res_false = director.process({"text": False}, {})
    assert res_false["stance"] == "NEUTRAL"
    assert res_false["summary"] == "Validation Error"
    assert "query text must be a string" in res_false["detail"]

    # text: 0
    res_zero = director.process({"text": 0}, {})
    assert res_zero["stance"] == "NEUTRAL"
    assert res_zero["summary"] == "Validation Error"
    assert "query text must be a string" in res_zero["detail"]


def test_init_super_model_registry_failure():
    """親クラスの初期化中（super().__init__）に model_registry で例外が発生した場合でも、
    Directorがクラッシュせずにデフォルト値で初期化されフォールバックされること"""
    # agents.agent_base.get_model をパッチして例外を発生させる
    with patch("agents.agent_base.get_model", side_effect=RuntimeError("Supervisor model resolution failed")), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        
        director = Director()
        assert director.model_name == "gemini-2.5-flash"
        assert director.name == "Director"
        assert director.role == "Creative Director"
        assert director.color == "#3B82F6"


def test_build_system_prompt_branding_keys_none():
    """branding_manager.constitution 内の keys が存在していても値が None の場合、デフォルト値にフォールバックされること"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_bm = MagicMock()
    mock_bm.constitution = {
        "channel_name": None,
        "visual_identity": {"style_prompt": None},
        "brand_personality": {"tone": None}
    }
    
    with patch("agents.director.branding_manager", mock_bm):
        sys_prompt = director._build_system_prompt(input_data, None)
        assert "Creative Channel" in sys_prompt  # デフォルトのチャネル名
        assert "Modern Creative Style" in sys_prompt  # デフォルトのスタイル
        assert "Friendly and engaging" in sys_prompt  # デフォルトのトーン
        assert "None" not in sys_prompt  # "None" がプロンプトに埋め込まれていないこと


def test_process_response_overwrites_agent_metadata(mock_branding_manager):
    """LLMがレスポンスにエージェントのメタデータキーを含めて返してきた場合でも、ベースレスポンス側の値が上書きされないこと"""
    director = Director()
    input_data = {"text": "Metadata Test Query"}
    
    mock_response = MagicMock()
    # 悪意ある、あるいは予期せぬキーの上書きが含まれるレスポンス
    mock_response.text = json.dumps({
        "agent": "HackerAgent",
        "role": "Spy",
        "color": "#000000",
        "stance": "AGREE",
        "summary": "Verified details",
        "detail": "Advises as Director"
    })
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["agent"] == "Director"
        assert res["role"] == "Creative Director"
        assert res["color"] == "#3B82F6"
        assert res["stance"] == "AGREE"


def test_init_director_model_registry_failure():
    """Directorの初期化中、get_model("director")呼び出し時に例外が発生した場合でも、
    クラッシュせずにデフォルト値で初期化されフォールバックされること"""
    # model_registry.get_model をパッチして例外を発生させる
    with patch("model_registry.get_model", side_effect=RuntimeError("Director model resolution failed")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"

