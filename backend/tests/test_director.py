import sys
import os
import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from agents.director import Director

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
        
        # 行番号を直接ハードコードせず、呼び出し時のキーワード引数を確認する
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        assert call_kwargs["file_path"] == "agents/director.py"
        assert call_kwargs["pattern"] == "process try-except block"
        assert call_kwargs["line_number"] > 0
        assert "LLM offline" in call_kwargs["notes"]

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
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
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
        assert "in Director process" in call_kwargs["notes"]


def test_director_custom_exceptions_and_types_defined():
    """ステップ1/3の設計：カスタム例外と型定義が正しくインポート可能であり、動作することを確認"""
    from agents.director import (
        DirectorError,
        DirectorValidationError,
        DirectorLLMError,
        DirectorInput,
        DirectorResponse
    )
    
    # 例外がExceptionを継承していることを検証
    assert issubclass(DirectorError, Exception)
    assert issubclass(DirectorValidationError, DirectorError)
    assert issubclass(DirectorLLMError, DirectorError)
    
    # 実際に送出可能かテスト
    with pytest.raises(DirectorValidationError):
        raise DirectorValidationError("Test validation error")
        
    with pytest.raises(DirectorLLMError):
        raise DirectorLLMError("Test LLM error")

    # 型定義(TypedDict)のキー構造を確認
    input_keys = DirectorInput.__annotations__.keys()
    assert "text" in input_keys
    assert "mode" in input_keys
    
    response_keys = DirectorResponse.__annotations__.keys()
    assert "agent" in response_keys
    assert "stance" in response_keys
    assert "summary" in response_keys
    assert "detail" in response_keys

# --- 新規追加テストケース (エラーハンドリング強化の検証) ---
def test_process_validation_error_raised(mock_branding_manager):
    """無効なモードの時などに DirectorValidationError が発生し、TDRに登録されずに Validation Error を返すことを検証"""
    director = Director()
    input_data = {"mode": "invalid_mode", "text": "Valid text"}
    
    with patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "Validation Error"
        assert "Invalid mode 'invalid_mode'" in res["detail"]
        mock_register.assert_not_called()

def test_process_llm_error_raised(mock_branding_manager):
    """LLMが空応答を返した時に DirectorLLMError が発生し、TDRに登録され、システムエラー応答が返ることを検証"""
    director = Director()
    input_data = {"text": "LLM Error Query"}
    
    mock_response = MagicMock()
    mock_response.text = "" # 空のレスポンス
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "LLM returned an empty or invalid response" in res["detail"]
        
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"


def test_process_invalid_text_type_raises_validation_error(mock_branding_manager):
    """text に文字列以外（例: 辞書やリスト）を渡した場合に適切に DirectorValidationError が発生すること"""
    director = Director()
    
    # text as dict
    input_data = {"text": {"invalid": "type"}}
    res = director.process(input_data, {})
    assert res["stance"] == "NEUTRAL"
    assert res["summary"] == "Validation Error"
    assert "query text must be a string" in res["detail"]

    # text as int
    input_data = {"text": 12345}
    res = director.process(input_data, {})
    assert res["stance"] == "NEUTRAL"
    assert res["summary"] == "Validation Error"
    assert "query text must be a string" in res["detail"]

def test_parse_response_with_missing_or_invalid_fields_fallback(mock_branding_manager):
    """AIのレスポンスで summary や detail が欠落している、あるいは型が異なる場合に安全にフォールバックされること"""
    director = Director()
    input_data = {"text": "Test input query"}
    
    # summary and detail are missing
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "演出方針に同意します (Approved)"
        assert res["detail"] == "演出の詳細アドバイスは提供されませんでした。"

    # summary is a dict, detail is an int (invalid types)
    mock_response2 = MagicMock()
    mock_response2.text = '{"stance": "DISAGREE", "summary": {"invalid": "type"}, "detail": 9999}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response2), \
         patch.object(director, "recall", return_value=None):
         
        res2 = director.process(input_data, {})
        assert res2["stance"] == "DISAGREE"
        assert res2["summary"] == "演出の修正を推奨します (Revision recommended)"
        assert res2["detail"] == "演出の詳細アドバイスは提供されませんでした。"

def test_parse_response_with_invalid_glossary_fallback(mock_branding_manager):
    """glossary に文字列以外の要素が含まれる、あるいは glossary 自体の型が不正な場合に安全に処理されること"""
    director = Director()
    input_data = {"text": "Test input query"}
    
    # glossary contains int and dict, should be cast to string
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "Verd", "detail": "Det", "glossary": [123, {"k": "v"}]}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["glossary"] == ["123", "{'k': 'v'}"]

    # glossary is a string instead of a list, should fallback to empty list
    mock_response2 = MagicMock()
    mock_response2.text = '{"stance": "AGREE", "summary": "Verd", "detail": "Det", "glossary": "invalid_glossary_type"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response2), \
         patch.object(director, "recall", return_value=None):
         
        res2 = director.process(input_data, {})
        assert res2["stance"] == "AGREE"
        assert res2["glossary"] == []

# --- 追加テストケース (APIError のキャッチと e.__traceback__ の検証) ---

def test_process_api_error_raises_llm_error(mock_branding_manager):
    """APIError が発生したときに、正しく DirectorLLMError にラップされ、最終的に System Error 応答を返すことを検証"""
    from google.genai.errors import APIError
    director = Director()
    input_data = {"text": "Gemini API Error Query"}
    
    # APIError のモックオブジェクトを作成 (APIError は通常、レスポンスやステータスコード等を持つ)
    mock_api_error = APIError("API rate limit exceeded", response_json={})
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=mock_api_error), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Gemini API Error" in res["detail"]
        
        # TDRに登録されていることの検証
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        assert "in Director process" in call_kwargs["notes"]


def test_register_tdr_with_traceback(mock_branding_manager):
    """e.__traceback__ を経由して例外発生箇所(行番号・ファイル)が正しくTDRに登録されることを検証"""
    director = Director()
    
    # 意図的に例外をスローさせ、トレースバックを保持した例外オブジェクトを作る
    try:
        raise ValueError("Simulated ValueError for traceback test")
    except ValueError as val_err:
        target_err = val_err

    # _register_tdr を呼び出す
    with patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        director._register_tdr(target_err)
        
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"
        # 実行ファイル名は agents/director.py にフォールバックされるか、あるいは実行時フレームから特定される
        assert "director.py" in call_kwargs["file_path"]
        assert call_kwargs["line_number"] > 0
        assert "Simulated ValueError" in call_kwargs["notes"]


def test_call_llm_unexpected_exception_wrapped(mock_branding_manager):
    """_call_llm で APIError 以外の予期せぬ例外が発生した際に、DirectorLLMError にラップされ TDR に登録されることを検証"""
    director = Director()
    input_data = {"text": "Unexpected Exception Query"}
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", side_effect=RuntimeError("Unexpected DB failure")), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Unexpected DB failure" in res["detail"]
        assert mock_register.call_count == 1

def test_parse_and_validate_response_unexpected_exception_wrapped(mock_branding_manager):
    """_parse_and_validate_response で予期せぬ例外が発生した際に、DirectorLLMError にラップされ TDR に登録されることを検証"""
    director = Director()
    input_data = {"text": "Parse error Query"}
    
    mock_response = MagicMock()
    mock_response.text = "{}"
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch("json.loads", side_effect=TypeError("Expected string or buffer")), \
         patch.object(director, "recall", return_value=None), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        res = director.process(input_data, {})
        assert res["stance"] == "NEUTRAL"
        assert res["summary"] == "System Error"
        assert "Expected string or buffer" in res["detail"]
        assert mock_register.call_count == 1

def test_process_missing_glossary_sets_default(mock_branding_manager):
    """AI応答に glossary が含まれない場合でも、デフォルトで空のリストが設定されることを検証"""
    director = Director()
    input_data = {"text": "Query text without glossary"}
    
    mock_response = MagicMock()
    # glossary が欠落している JSON 応答
    mock_response.text = '{"stance": "AGREE", "summary": "Verdict", "detail": "Advice"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert "glossary" in res
        assert res["glossary"] == []


def test_register_tdr_absolute_path_resolved(mock_branding_manager):
    """_register_tdr に絶対パスのエラーファイルを渡した場合に、それが正しくプロジェクト相対パスに変換されることを検証"""
    director = Director()
    
    # 偽の絶対パスの例外トレースバックを作成
    class MockFrame:
        def __init__(self, filename, lineno):
            self.filename = filename
            self.lineno = lineno

    import os
    # agents/director.py の絶対パスを構築
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_file = os.path.join(backend_dir, "agents", "director.py").replace("\\", "/")
    
    mock_frame = MockFrame(abs_file, 88)
    
    with patch("traceback.extract_tb", return_value=[mock_frame]), \
         patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        # 本物のトレースバックオブジェクトを取得してダミー例外に設定
        try:
            raise ValueError("Dummy exception to extract traceback")
        except ValueError as err:
            real_tb = err.__traceback__
            
        dummy_exc = ValueError("Test absolute path resolution")
        dummy_exc.__traceback__ = real_tb
        
        director._register_tdr(dummy_exc)
        
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        
        # 相対パスに変換されていること
        assert call_kwargs["file_path"] == "agents/director.py"


# --- さらに追加したテストケース (新規エラーハンドリングと堅牢化の検証) ---

def test_init_model_registry_general_exception_fallback(mock_branding_manager):
    """model_registry.get_modelが一般的な例外を投げた際、デフォルトのモデルに安全にフォールバックすること"""
    with patch("model_registry.get_model", side_effect=RuntimeError("Registry DB connection failed")):
        # Directorをインスタンス化するとget_modelが呼ばれ、例外が発生するはず
        director = Director()
        assert director.model_name == "gemini-2.5-flash"

def test_process_invalid_context_type_handled(mock_branding_manager):
    """context引数に辞書以外のオブジェクトを渡した際、例外をスローせず安全に処理が完了すること"""
    director = Director()
    input_data = {"text": "Valid query"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE", "summary": "Looks good", "detail": "Details"}'
    
    with patch("agents.director.HAS_ADK", False),          patch.object(director.client.models, "generate_content", return_value=mock_response),          patch.object(director, "recall", return_value=None):
         
        # context as list
        res_list = director.process(input_data, ["invalid", "context", "type"])
        assert res_list["stance"] == "AGREE"
        
        # context as string
        res_str = director.process(input_data, "invalid_context_string")
        assert res_str["stance"] == "AGREE"

def test_register_tdr_traceback_with_cause(mock_branding_manager):
    """__cause__ を持つラップされた例外オブジェクトを _register_tdr に渡した際、原因となった元の例外の行番号とファイル名が TDR に正しく渡されること"""
    director = Director()
    
    # 元のエラーをシミュレートするトレースバックを持つ例外オブジェクト
    class MockFrame:
        def __init__(self, filename, lineno):
            self.filename = filename
            self.lineno = lineno
            
    mock_frame = MockFrame("my_module/sub_file.py", 42)
    
    with patch("traceback.extract_tb", return_value=[mock_frame]),          patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
         
        # ダミーの元のエラーと、それを cause として持つ新しいエラーを作る
        try:
            raise ValueError("Original Error")
        except ValueError as err1:
            try:
                raise RuntimeError("Wrapped Error") from err1
            except RuntimeError as err2:
                target_err = err2
                
        director._register_tdr(target_err)
        
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        assert "sub_file.py" in call_kwargs["file_path"]
        assert call_kwargs["line_number"] == 42
        assert "Wrapped Error" in call_kwargs["notes"] or "Original Error" in call_kwargs["notes"]

def test_register_tdr_path_resolution_exception_logged(mock_branding_manager):
    """プロジェクトパス変換時に例外が発生した際、黙殺されずに警告ログが出力されること"""
    director = Director()
    
    # 意図的に例外をスローさせるために、例外オブジェクトを作る
    try:
        raise ValueError("TDR Test Error")
    except ValueError as val_err:
        target_err = val_err

    # os.path.relpath で例外を発生させて、警告ログをアサートする
    with patch("os.path.relpath", side_effect=TypeError("Expected path-like object")),          patch("traceback.extract_tb") as mock_tb,          patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt"):
         
        class MockFrame:
            def __init__(self):
                self.filename = "C:/Absolute/Path/agents/director.py"
                self.lineno = 100
                
        mock_tb.return_value = [MockFrame()]
        
        with patch("logging.Logger.warning") as mock_warn:
            director._register_tdr(target_err)
            assert mock_warn.call_count >= 1
            log_msg = mock_warn.call_args[0][0]
            assert "Failed to resolve project relative path" in log_msg

def test_parse_response_missing_summary_default_stance_agree(mock_branding_manager):
    """AIレスポンスに summary と detail がなく、stance が AGREE の場合、スタンスに応じたデフォルトサマリーが適用されることを検証"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "AGREE"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "AGREE"
        assert res["summary"] == "演出方針に同意します (Approved)"
        assert res["detail"] == "演出の詳細アドバイスは提供されませんでした。"

def test_parse_response_missing_summary_default_stance_disagree(mock_branding_manager):
    """AIレスポンスに summary と detail がなく、stance が DISAGREE の場合、スタンスに応じたデフォルトサマリーが適用されることを検証"""
    director = Director()
    input_data = {"text": "Test Query"}
    
    mock_response = MagicMock()
    mock_response.text = '{"stance": "DISAGREE"}'
    
    with patch("agents.director.HAS_ADK", False), \
         patch.object(director.client.models, "generate_content", return_value=mock_response), \
         patch.object(director, "recall", return_value=None):
         
        res = director.process(input_data, {})
        assert res["stance"] == "DISAGREE"
        assert res["summary"] == "演出の修正を推奨します (Revision recommended)"
        assert res["detail"] == "演出の詳細アドバイスは提供されませんでした。"

def test_register_tdr_fallback_inspect(mock_branding_manager):
    """traceback が取得できない場合、inspect モジュールにより呼び出し元のファイルと行番号が取得されて TDR に登録されることを検証"""
    director = Director()
    
    # traceback がないダミーエラーを作る
    target_err = ValueError("Inspect Test Error")
    target_err.__traceback__ = None
    
    with patch("agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        director._register_tdr(target_err)
        
        assert mock_register.call_count == 1
        call_kwargs = mock_register.call_args[1]
        
        # 呼び出し元が test_director.py になるはず
        assert "test_director.py" in call_kwargs["file_path"]
        assert isinstance(call_kwargs["line_number"], int)
        assert call_kwargs["category"] == "IMPORTANT_SERVICE"


def test_parse_response_invalid_stance_summary_fallback(mock_branding_manager):
    """AI応答の stance が無効で summary も欠落している場合、stanceがNEUTRALになり、かつsummaryもNo opinionになることを検証"""
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


def test_init_model_registry_import_error_fallback():
    """__init__ で model_registry がインポートできない場合に ImportError をキャッチして gemini-2.5-flash にフォールバックし、属性が正しく設定されることを確認"""
    with patch("model_registry.get_model", side_effect=ImportError("Registry missing")):
        director = Director()
        assert director.model_name == "gemini-2.5-flash"
        assert director.name == "Director"
        assert director.role == "Creative Director"
        assert director.color == "#3B82F6"
        assert hasattr(director, "client")

def test_init_super_failed_propagates():
    """__init__ で super().__init__ が失敗した場合に例外がキャッチされずにそのまま上位に伝播することを確認"""
    with patch("agents.agent_base.Agent.__init__", side_effect=RuntimeError("Base init failed")):
        with pytest.raises(RuntimeError, match="Base init failed"):
            Director()


