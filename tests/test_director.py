import sys
import os
import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from agents.director import Director, DirectorLLMError

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
        "channel_name": "TestChannel",
        "visual_identity": {"style_prompt": "TestStyle"},
        "brand_personality": {"tone": "TestTone"}
    }
    with patch("agents.director.branding_manager", mock_bm):
        yield mock_bm

def test_init_success():
    """初期化が正常に成功することを確認"""
    director = Director()
    assert director.name == "Director"
    assert director.role == "Creative Director"
    assert director.color == "#3B82F6"

def test_process_pre_production_genai(mock_branding_manager):
    """HAS_ADK = False の状況で、pre_production モードでの正常なコンテンツ生成"""
    director = Director()
    input_data = {"mode": "pre_production", "text": "Test input query"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "Great preprod idea", "detail": "Details of visual hooks", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        
        assert res["stance"] == "AGREE"
        assert res["summary"] == "Great preprod idea"
        assert res["detail"] == "Details of visual hooks"
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        assert kwargs.get("contents") == "Test input query"
        sys_instr = kwargs.get("config").system_instruction
        assert "MODE: PRE-PRODUCTION" in sys_instr

def test_process_post_production_genai(mock_branding_manager):
    """HAS_ADK = False の状況で、post_production モードでの正常なコンテンツ生成"""
    director = Director()
    input_data = {"mode": "post_production", "text": "Editing query"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "DISAGREE", "summary": "Too slow pacing", "detail": "Add B-rolls", "glossary": []}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        
        assert res["stance"] == "DISAGREE"
        assert res["summary"] == "Too slow pacing"
        assert res["detail"] == "Add B-rolls"
        mock_generate.assert_called_once()
        args, kwargs = mock_generate.call_args
        assert kwargs.get("contents") == "Editing query"
        sys_instr = kwargs.get("config").system_instruction
        assert "MODE: POST-PRODUCTION" in sys_instr

def test_process_with_recalled_lessons(mock_branding_manager):
    """過去のレッスン想起結果がプロンプトに注入されることを確認"""
    director = Director()
    input_data = {"text": "Query text"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "NEUTRAL", "summary": "Neutral summary", "detail": "Detail advice", "glossary": []}'
    
    lessons = [{"feedback": "More contrast in thumbnails"}]
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=lessons) as mock_recall:
         
        res = director.process(input_data, {})
        
        mock_recall.assert_called_once_with("Query text")
        args, kwargs = mock_generate.call_args
        sys_instr = kwargs.get("config").system_instruction
        assert "More contrast in thumbnails" in sys_instr

def test_process_with_council_context(mock_branding_manager):
    """council_context を受け取った場合、連携インサイトが注入されることを確認"""
    director = Director()
    input_data = {"text": "Query text"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "NEUTRAL", "summary": "Neutral summary", "detail": "Detail advice", "glossary": []}'
    
    council_context = {"analyst_findings": "High CTR predicted"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response) as mock_generate, \
         patch.object(director, "recall", return_value=None), \
         patch.object(director, "_inject_council_findings", return_value="Council Findings: High CTR predicted") as mock_inject:
         
        res = director.process(input_data, {}, council_context=council_context)
        
        mock_inject.assert_called_once_with(council_context)
        args, kwargs = mock_generate.call_args
        sys_instr = kwargs.get("config").system_instruction
        assert "Council Findings: High CTR predicted" in sys_instr

def test_process_adk_success(mock_branding_manager):
    """HAS_ADK = True 時、ADK 関連クラスが正しく呼び出され、レスポンスが生成されることを確認"""
    director = Director()
    input_data = {"text": "ADK Query"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_adk_response = {
        "stance": "AGREE",
        "summary": "ADK creative verdict",
        "detail": "ADK detailed advice",
        "glossary": ["keyterm"]
    }
    
    mock_part = MagicMock()
    mock_part.text = "```json\n" + json.dumps(mock_adk_response) + "\n```"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent") as mock_adk_agent, \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner) as mock_runner_class, \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        
        assert res["stance"] == "AGREE"
        assert res["summary"] == "ADK creative verdict"
        assert res["detail"] == "ADK detailed advice"
        assert res["glossary"] == ["keyterm"]

def test_process_adk_markdown_without_json(mock_branding_manager):
    """ADK が json 指定のない ``` コードブロックで返してきたケース"""
    director = Director()
    input_data = {"text": "ADK Query"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_adk_response = {
        "stance": "AGREE",
        "summary": "ADK plain block verdict",
        "detail": "ADK plain details"
    }
    
    mock_part = MagicMock()
    mock_part.text = "```\n" + json.dumps(mock_adk_response) + "\n```"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "ADK plain block verdict"

def test_process_adk_list_response(mock_branding_manager):
    """ADK がリスト形式のJSONを返してきたケース（最初の要素が抽出されること）"""
    director = Director()
    input_data = {"text": "ADK List Query"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_adk_response = [{
        "stance": "DISAGREE",
        "summary": "First item in list",
        "detail": "List detail"
    }]
    
    mock_part = MagicMock()
    mock_part.text = json.dumps(mock_adk_response)
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert res["summary"] == "First item in list"

def test_process_adk_empty_list_response(mock_branding_manager):
    """ADK が空のリストを返してきたケース（空辞書としてベースレスポンスにマージされ、追加キーが存在しないこと）"""
    director = Director()
    input_data = {"text": "ADK Empty Query"}
    
    mock_event = MagicMock()
    mock_event.is_final_response.return_value = True
    
    mock_part = MagicMock()
    mock_part.text = "[]"
    mock_event.content.parts = [mock_part]
    
    mock_runner = MagicMock()
    mock_runner.run.return_value = [mock_event]
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", return_value=mock_runner), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "No opinion"
        assert res["agent"] == "Director"

def test_process_invalid_type_raises_value_error(mock_branding_manager):
    """JSONデコード後の結果がディクショナリ/リスト以外（例: 数値）の場合、ValueErrorとなりシステムエラーとしてフォールバックされること"""
    director = Director()
    input_data = {"text": "Invalid JSON Query"}
    
    mock_response = MagicMock()
    mock_response.text = "12345"
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Failed to consult the Director" in res["detail"]

def test_process_http_exception_propagates(mock_branding_manager):
    """HTTPException がスローされた場合、キャッチされずに上位に透過的に raise されること"""
    director = Director()
    input_data = {"text": "HTTP Exception Query"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=HTTPException(status_code=403, detail="Forbidden")), \
         patch.object(director, "recall", return_value=None):
         
        with pytest.raises(HTTPException) as excinfo:
            director.process(input_data, {})
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Forbidden"

def test_process_general_exception_fallback(mock_branding_manager):
    """一般的な Exception がスローされた場合、キャッチされてシステムエラー応答が返されること"""
    director = Director()
    input_data = {"text": "General Exception Query"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=RuntimeError("LLM offline")), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "LLM offline" in res["detail"]

def test_process_general_exception_registers_tdr(mock_branding_manager):
    """一般的な Exception がスローされた場合、TDR に技術負債が登録されることを検証"""
    director = Director()
    input_data = {"text": "TDR Exception Query"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=RuntimeError("LLM offline")), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        
        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        assert call_kwargs["file_path"] == "agents/director.py"
        assert isinstance(call_kwargs["line_number"], int)
        assert call_kwargs["pattern"] == "process try-except block"
        assert "Error (RuntimeError) in Director process: LLM offline" in call_kwargs["notes"]

def test_process_invalid_input_data_raises_validation_error(mock_branding_manager):
    """input_data が辞書ではない場合、早期リターンして Validation Error を返すことを検証"""
    director = Director()
    
    # input_data as None
    res = director.process(None, {})
    assert res["stance"] == "NEUTRAL"
    assert res["summary"] == "Validation Error"
    assert "input_data must be a dictionary" in res["detail"]

    # input_data as list
    res = director.process([], {})
    assert res["stance"] == "NEUTRAL"
    assert res["summary"] == "Validation Error"
    assert "input_data must be a dictionary" in res["detail"]

def test_process_json_decode_error_registers_tdr(mock_branding_manager):
    """AI応答のJSONデコードに失敗した場合、ValueErrorが発生してシステムエラーになり、かつTDRに技術負債が登録されることを検証"""
    director = Director()
    input_data = {"text": "JSON Decode Error Query"}
    
    mock_response = MagicMock()
    mock_response.text = "{invalid_json"
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response),          patch.object(director, "recall", return_value=None),          patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Failed to consult the Director" in res["detail"]
        
        # Verify that register_debt was called once
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        assert call_kwargs["file_path"] == "agents/director.py"
        assert call_kwargs["pattern"] == "process try-except block"
        assert "Error (DirectorLLMError) in Director process: No JSON structure found in AI response" in call_kwargs["notes"]


def test_parse_and_validate_response_invalid_type(mock_branding_manager):
    """_parse_and_validate_response に文字列以外の型（None や int など）が渡された場合、DirectorLLMError が発生することを確認"""
    director = Director()
    with pytest.raises(DirectorLLMError) as excinfo:
        director._parse_and_validate_response(None)
    assert "AI response must be a string" in str(excinfo.value)

    with pytest.raises(DirectorLLMError) as excinfo:
        director._parse_and_validate_response(12345)
    assert "AI response must be a string" in str(excinfo.value)

def test_process_value_error_fallback(mock_branding_manager):
    """process 内で ValueError が発生した場合、専用の catch ブロックで処理され、かつTDRに技術負債が登録されることを検証"""
    director = Director()
    input_data = {"text": "Value Error Query"}
    
    # generate_content で ValueError を発生させる
    with patch("agents.director.HAS_ADK", False),          patch.object(director.client.models, "generate_content", side_effect=ValueError("Invalid parameter value")),          patch.object(director, "recall", return_value=None),          patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "(Value Error)" in res["detail"]
        assert "Invalid parameter value" in res["detail"]
        
        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        assert call_kwargs["file_path"] == "agents/director.py"
        assert isinstance(call_kwargs["line_number"], int)
        assert call_kwargs["pattern"] == "process try-except block"
        assert "Error (ValueError) in Director process: Invalid parameter value" in call_kwargs["notes"]


def test_process_value_error_adk_transparency(mock_branding_manager):
    """ADKモード実行時に ValueError が発生した場合、透過して process の ValueError ブロックで処理されること"""
    director = Director()
    input_data = {"text": "ADK Value Error Query"}
    
    with patch("agents.director.HAS_ADK", True), \
         patch("google.adk.agents.Agent"), \
         patch("google.adk.runners.InMemoryRunner", side_effect=ValueError("ADK Value Error")), \
         patch("google.adk.agents.run_config.RunConfig"), \
         patch("google.genai.types.Content"), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "(Value Error)" in res["detail"]
        assert "ADK Value Error" in res["detail"]
        mock_register.assert_called_once()


def test_register_tdr_nested_exception_chain(mock_branding_manager):
    """例外が多重にネストしたチェイン (A from B from C) になっている場合、e.__cause__ で最奥の原因例外を辿り、正しく TDR に登録されること"""
    director = Director()
    
    try:
        try:
            try:
                raise RuntimeError("Deepest Root Cause")
            except RuntimeError as e1:
                raise ValueError("Middle Exception") from e1
        except ValueError as e2:
            raise DirectorLLMError("Outer LLM Error") from e2
    except DirectorLLMError as e3:
        target_exception = e3
        
    with patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        director._register_tdr(target_exception)
        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args[1]
        
        # 明示的なチェインを遡って、最奥の RuntimeError が notes に記録されていることを確認
        assert "RuntimeError" in call_kwargs["notes"]
        assert "Deepest Root Cause" in call_kwargs["notes"]


def test_init_model_registry_specific_exceptions():
    """初期化時に model_registry からのインポートエラーやその他の指定例外が発生した場合、デフォルトにフォールバックされること"""
    # ImportError
    with patch("model_registry.get_model", side_effect=ImportError("Mock Import Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"
        
    # ValueError
    with patch("model_registry.get_model", side_effect=ValueError("Mock Value Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"

    # TypeError
    with patch("model_registry.get_model", side_effect=TypeError("Mock Type Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"

    # RuntimeError
    with patch("model_registry.get_model", side_effect=RuntimeError("Mock Runtime Error")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"


def test_call_llm_response_text_value_error(mock_branding_manager):
    """response.text アクセス時に ValueError（安全ブロックなど）が発生した場合、DirectorLLMError に変換されてシステムエラーとして処理されること"""
    director = Director()
    input_data = {"text": "Blocked query"}
    
    mock_response = MagicMock()
    # .text プロパティへのアクセス時に ValueError を発生させる
    type(mock_response).text = property(MagicMock(side_effect=ValueError("Safety block")))
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Failed to consult the Director" in res["detail"]
        
        # TDRに登録されることの検証
        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args[1]
        assert "ValueError" in call_kwargs["notes"]
        assert "Safety block" in call_kwargs["notes"]


def test_parse_response_invalid_stance_summary_fallback(mock_branding_manager):
    """AI応答の stance が無効で summary も欠落している場合、stanceがNEUTRALなり、かつsummaryもNo opinionになることを検証"""
    director = Director()
    input_data = {"text": "Invalid Stance Query"}
    
    mock_response = MagicMock()
    # stance が無効値であり、かつ summary/detail/glossary が欠落しているJSON
    mock_response.text = '{"stance": "INVALID_VALUE"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "No opinion"


