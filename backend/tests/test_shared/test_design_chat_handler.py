"""
Unit tests for Design Chat Handler (including edge cases, fallbacks, and boundary conditions)
"""
import sys
import pytest
import json
from unittest.mock import patch, MagicMock

def test_dch_01_init():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    assert handler is not None

def test_dch_02_get_model_fallback():
    # design_system.design_chat_handler がロードされるときの ImportError をシミュレート
    with patch.dict(sys.modules, {'model_registry': None}):
        # sys.modules からキャッシュを削除して再インポートを促す
        for key in list(sys.modules.keys()):
            if "design_chat_handler" in key:
                del sys.modules[key]
        
        from design_system.design_chat_handler import get_model
        # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
        # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
        from model_policy import resolve
        assert get_model("any_task") == resolve("any_task").model
        assert not get_model("any_task").startswith("gemini-2.5")

def test_dch_03_design_token_manager_lazy_load():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    assert handler._design_token_manager is None
    manager = handler.design_token_manager
    assert manager is not None
    assert handler._design_token_manager is not None

def test_dch_04_process_command_success():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_parsed = {"valid": True, "mood": "elegant", "updates": {"color_palette": {"primary": "#D4AF37"}}}
    with patch.object(handler, '_parse_with_ai', return_value=mock_parsed), \
         patch.object(handler.design_token_manager, 'update_tokens', return_value={"status": "success"}) as mock_update:
        
        res = handler.process_command("change primary color")
        assert res["status"] == "success"
        mock_update.assert_called_once_with(
            mood="elegant",
            updates={"color_palette": {"primary": "#D4AF37"}},
            source="chat",
            reason="change primary color"
        )

def test_dch_05_process_command_invalid_parsed():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_parsed = {"valid": False}
    with patch.object(handler, '_parse_with_ai', return_value=mock_parsed):
        res = handler.process_command("invalid command")
        assert res["status"] == "error"
        assert "コマンドを解析できませんでした" in res["message"]

def test_dch_06_process_command_no_updates():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_parsed = {"valid": True, "mood": "elegant", "updates": {}}
    with patch.object(handler, '_parse_with_ai', return_value=mock_parsed):
        res = handler.process_command("no updates")
        assert res["status"] == "error"
        assert "更新内容が見つかりませんでした" in res["message"]

def test_dch_07_parse_with_ai_json_markdown():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = '```json\n{"valid": true, "mood": "dynamic"}\n```'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client), \
         patch('design_system.design_chat_handler.get_model', return_value="mock-model"):
        res = handler._parse_with_ai("test cmd")
        assert res == {"valid": True, "mood": "dynamic"}

def test_dch_08_parse_with_ai_markdown_only():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = '```\n{"valid": true, "mood": "dramatic"}\n```'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
        res = handler._parse_with_ai("test cmd")
        assert res == {"valid": True, "mood": "dramatic"}

def test_dch_09_parse_with_ai_plain():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = '{"valid": true, "mood": "elegant"}'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
        res = handler._parse_with_ai("test cmd")
        assert res == {"valid": True, "mood": "elegant"}

def test_dch_10_parse_with_ai_json_decode_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = 'invalid json text'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client), \
         patch.object(handler, '_parse_simple', return_value={"fallback": True}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": True}
        mock_simple.assert_called_once_with("test cmd")

def test_dch_11_parse_with_ai_unexpected_exception():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API Error")
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client), \
         patch.object(handler, '_parse_simple', return_value={"fallback": True}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": True}
        mock_simple.assert_called_once_with("test cmd")

def test_dch_12_parse_simple_moods():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    assert handler._parse_simple("ダイナミックな感じ")["mood"] == "dynamic"
    assert handler._parse_simple("ドラマチックな映像")["mood"] == "dramatic"
    assert handler._parse_simple("エレガントな演出")["mood"] == "elegant"

def test_dch_13_parse_simple_colors():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # プライマリ（日本語）
    res = handler._parse_simple("プライマリカラーをゴールドに変更")
    assert res["valid"] is True
    assert res["updates"]["color_palette"] == {"primary": "#D4AF37"}
    
    # プライマリ（英語＋日本語色名）
    res = handler._parse_simple("primary color to シルバー")
    assert res["valid"] is True
    assert res["updates"]["color_palette"] == {"primary": "#C0C0C0"}
    
    # セカンダリ（日本語）
    res = handler._parse_simple("セカンダリカラーをネイビーに")
    assert res["valid"] is True
    assert res["updates"]["color_palette"] == {"secondary": "#2C3E50"}

    # セカンダリ（英語＋日本語色名）
    res = handler._parse_simple("secondary color to レッド")
    assert res["valid"] is True
    assert res["updates"]["color_palette"] == {"secondary": "#E74C3C"}
    
    # 一致しない場合
    res = handler._parse_simple("何もしない")
    assert res["valid"] is False

def test_dch_14_get_current_tokens_summary():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_tokens = {
        "color_palette": {
            "primary": "#D4AF37",
            "secondary": "#C0C0C0"
        },
        "imagen_prompt_suffix": "elegant, luxury"
    }
    
    with patch.object(handler.design_token_manager, 'get_tokens', return_value=mock_tokens):
        summary = handler.get_current_tokens_summary("elegant")
        assert "## Elegant デザイントークン" in summary
        assert "### color_palette" in summary
        assert "- primary: `#D4AF37`" in summary
        assert "- secondary: `#C0C0C0`" in summary
        assert "- imagen_prompt_suffix: `elegant, luxury`" in summary

def test_dch_15_parse_simple_all_colors():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 全色マッピングのテーブル駆動テスト
    for color_name, hex_code in handler.COLOR_MAPPING.items():
        # プライマリのテスト
        res_p = handler._parse_simple(f"primary {color_name}")
        assert res_p["valid"] is True
        assert res_p["updates"]["color_palette"]["primary"] == hex_code
        
        # セカンダリのテスト
        res_s = handler._parse_simple(f"secondary {color_name}")
        assert res_s["valid"] is True
        assert res_s["updates"]["color_palette"]["secondary"] == hex_code

def test_dch_16_parse_simple_multiple_colors():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 複数カラーがコマンドに含まれる場合、最後のマッチする色がプライマリ（コマンドに「プライマリ」が含まれるため）で上書きされる挙動を確認
    res = handler._parse_simple("プライマリカラーをゴールド、セカンダリカラーをシルバーに変更")
    assert res["valid"] is True
    # COLOR_MAPPINGのループ順に依存するが、"シルバー"（#C0C0C0）は"ゴールド"（#D4AF37）の後に処理されるため上書きされる
    assert res["updates"]["color_palette"]["primary"] == "#C0C0C0"

def test_dch_17_parse_simple_no_primary_secondary():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 色名のみでプライマリ/セカンダリの指定がない場合
    res = handler._parse_simple("ゴールドに変更")
    assert res["valid"] is False
    assert "color_palette" not in res["updates"]

def test_dch_18_parse_with_ai_missing_closing_backticks():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 閉じバッククォートが欠落している場合でもパースできるか
    mock_response = MagicMock()
    mock_response.text = '```json\n{"valid": true, "mood": "elegant", "updates": {"imagen_prompt_suffix": "test"}}'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
        res = handler._parse_with_ai("test cmd")
        assert res == {"valid": True, "mood": "elegant", "updates": {"imagen_prompt_suffix": "test"}}

def test_dch_19_parse_with_ai_multiple_json_blocks():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 複数ブロックある場合、最初のブロックが取得されるか
    mock_response = MagicMock()
    mock_response.text = '```json\n{"valid": true}\n```\n```json\n{"valid": false}\n```'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
        res = handler._parse_with_ai("test cmd")
        assert res == {"valid": True}

def test_dch_20_parse_with_ai_invalid_markdown_brackets():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 無効な markdown (``` が1箇所のみで split[1] が IndexError になるケース)
    mock_response = MagicMock()
    mock_response.text = '```'
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client), \
         patch.object(handler, '_parse_simple', return_value={"fallback": True}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": True}
        mock_simple.assert_called_once_with("test cmd")

def test_dch_21_get_current_tokens_summary_default():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 引数を明示的に指定しない場合のデフォルト動作 (mood="elegant")
    mock_tokens = {"imagen_prompt_suffix": "elegant, luxury"}
    with patch.object(handler.design_token_manager, 'get_tokens', return_value=mock_tokens) as mock_get:
        summary = handler.get_current_tokens_summary()
        mock_get.assert_called_once_with("elegant")
        assert "## Elegant デザイントークン" in summary

def test_dch_22_get_current_tokens_summary_variations():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 空の辞書
    with patch.object(handler.design_token_manager, 'get_tokens', return_value={}):
        summary = handler.get_current_tokens_summary("elegant")
        assert summary == "## Elegant デザイントークン\n"

    # ネストしたdictのみ
    mock_tokens_dict = {"group1": {"key1": "val1"}}
    with patch.object(handler.design_token_manager, 'get_tokens', return_value=mock_tokens_dict):
        summary = handler.get_current_tokens_summary("elegant")
        assert "### group1" in summary
        assert "- key1: `val1`" in summary

    # プリミティブのみ
    mock_tokens_primitive = {"key2": "val2"}
    with patch.object(handler.design_token_manager, 'get_tokens', return_value=mock_tokens_primitive):
        summary = handler.get_current_tokens_summary("elegant")
        assert "- key2: `val2`" in summary

def test_dch_23_get_model_registry_loaded():
    # model_registry がインポート可能である場合のモックテスト
    import sys
    from unittest.mock import MagicMock
    
    mock_model_registry = MagicMock()
    mock_model_registry.get_model.return_value = "registry-model"
    
    with patch.dict(sys.modules, {'model_registry': mock_model_registry}):
        # sys.modules の design_chat_handler をクリアして再ロードさせる
        for key in list(sys.modules.keys()):
            if "design_chat_handler" in key:
                del sys.modules[key]
        
        from design_system.design_chat_handler import get_model
        assert get_model("branding") == "registry-model"
        mock_model_registry.get_model.assert_called_once_with("branding")


def test_dch_24_process_command_ai_returns_list_raises_attribute_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = '[]'  # JSON list
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client):
        with pytest.raises(AttributeError):
            handler.process_command("test command")

def test_dch_25_parse_with_ai_markdown_index_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_response = MagicMock()
    mock_response.text = None
    
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    
    with patch('gemini_client_factory.get_gemini_client', return_value=mock_client),          patch.object(handler, '_parse_simple', return_value={"fallback": True}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": True}
        mock_simple.assert_called_once_with("test cmd")

def test_dch_26_get_current_tokens_summary_non_string_values():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    mock_tokens = {
        "color_palette": {
            "primary": None,
            "opacity": 0.8
        },
        "list_value": [1, 2, 3]
    }
    
    with patch.object(handler.design_token_manager, 'get_tokens', return_value=mock_tokens):
        summary = handler.get_current_tokens_summary("dynamic")
        assert "## Dynamic デザイントークン" in summary
        assert "- primary: `None`" in summary
        assert "- opacity: `0.8`" in summary
        assert "- list_value: `[1, 2, 3]`" in summary

def test_dch_27_get_current_tokens_summary_mood_casing():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    with patch.object(handler.design_token_manager, 'get_tokens', return_value={}):
        summary = handler.get_current_tokens_summary("dRaMaTiC")
        assert "## Dramatic デザイントークン" in summary

def test_dch_28_parse_simple_empty_command():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    res = handler._parse_simple("")
    assert res["valid"] is False
    assert res["mood"] == "elegant"
    assert res["updates"] == {}


def test_dch_29_parse_with_ai_import_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # ImportError を発生させるために、モジュールのインポートで例外を起こす
    with patch("gemini_client_factory.get_gemini_client", side_effect=ImportError("Mocked import error")):
        with patch.object(handler, '_parse_simple', return_value={"fallback": "import_error"}) as mock_simple:
            res = handler._parse_with_ai("test cmd")
            assert res == {"fallback": "import_error"}
            mock_simple.assert_called_once_with("test cmd")


def test_dch_30_parse_with_ai_api_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # APIError 例外が発生したときの挙動を確認
    mock_client = MagicMock()
    # APIError クラスを動的に定義してモックする
    class MockAPIError(Exception):
        pass
        
    mock_client.models.generate_content.side_effect = MockAPIError("API Error")
    
    # 内部で APIError としてキャッチされるよう、google.genai.errors.APIError を MockAPIError でパッチ
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client),          patch("google.genai.errors.APIError", MockAPIError, create=True),          patch.object(handler, '_parse_simple', return_value={"fallback": "api_error"}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": "api_error"}
        mock_simple.assert_called_once_with("test cmd")


def test_dch_31_parse_with_ai_attribute_error():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # AttributeError (response が None など) のテスト
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = None  # NoneResponse
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client),          patch.object(handler, '_parse_simple', return_value={"fallback": "attribute_error"}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": "attribute_error"}
        mock_simple.assert_called_once_with("test cmd")


def test_dch_32_parse_with_ai_generic_exception():
    from design_system.design_chat_handler import DesignChatHandler
    handler = DesignChatHandler()
    
    # 予期せぬ Exception 発生と TDR 登録の確認
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("Unexpected crash")
    
    mock_td = MagicMock()
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client),          patch("agents.memory.technical_debt.technical_debt_store", mock_td),          patch.object(handler, '_parse_simple', return_value={"fallback": "generic_exception"}) as mock_simple:
        res = handler._parse_with_ai("test cmd")
        assert res == {"fallback": "generic_exception"}
        mock_simple.assert_called_once_with("test cmd")
        mock_td.register_debt.assert_called_once()

