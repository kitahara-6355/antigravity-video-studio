import sys
import os
import pytest
from unittest.mock import patch, MagicMock, mock_open
import runpy

# テスト対象のモジュールがインポートできるようにPATHを通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import verify_full_system

def test_log_success(capsys):
    """log_success 関数のテスト"""
    verify_full_system.log_success("テストメッセージ")
    captured = capsys.readouterr()
    assert "✅ PASS: テストメッセージ" in captured.out

def test_log_failure(capsys):
    """log_failure 関数のテスト (sys.exit(1) が発生することを確認)"""
    with pytest.raises(SystemExit) as excinfo:
        verify_full_system.log_failure("エラーメッセージ")
    
    captured = capsys.readouterr()
    assert "❌ FAIL: エラーメッセージ" in captured.out
    assert excinfo.value.code == 1

# ==========================================
# 分割された内部関数のテスト
# ==========================================

@patch("verify_full_system.requests.get")
def test_fetch_backend_status_success(mock_get):
    """_fetch_backend_statusの正常系テスト"""
    mock_res = MagicMock()
    mock_get.return_value = mock_res
    res = verify_full_system._fetch_backend_status()
    assert res == mock_res
    mock_get.assert_called_once_with("http://localhost:8000/api/status", timeout=10)

@patch("verify_full_system.requests.get")
def test_fetch_backend_status_failure(mock_get, capsys):
    """_fetch_backend_statusの異常系テスト（RequestException）"""
    import requests
    mock_get.side_effect = requests.exceptions.RequestException("Connection error")
    with pytest.raises(SystemExit):
        verify_full_system._fetch_backend_status()
    captured = capsys.readouterr()
    assert "Could not connect to backend: Connection error: Connection error" in captured.out

def test_parse_and_validate_status_response_success():
    """_parse_and_validate_status_responseの正常系テスト"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"status": "ok"}
    res = verify_full_system._parse_and_validate_status_response(mock_res)
    assert res == {"status": "ok"}

def test_parse_and_validate_status_response_non_200(capsys):
    """_parse_and_validate_status_responseの異常系テスト（非200）"""
    mock_res = MagicMock()
    mock_res.status_code = 500
    with pytest.raises(SystemExit):
        verify_full_system._parse_and_validate_status_response(mock_res)
    captured = capsys.readouterr()
    assert "Backend returned status code 500" in captured.out

def test_parse_and_validate_status_response_invalid_json(capsys):
    """_parse_and_validate_status_responseの異常系テスト（JSON不正）"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.side_effect = ValueError("JSON decode error")
    with pytest.raises(SystemExit):
        verify_full_system._parse_and_validate_status_response(mock_res)
    captured = capsys.readouterr()
    assert "Could not connect to backend: Invalid JSON response: JSON decode error" in captured.out

# check_backend_health のテスト
@patch("verify_full_system._fetch_backend_status")
@patch("verify_full_system._parse_and_validate_status_response")
def test_check_backend_health_success(mock_validate, mock_fetch, capsys):
    mock_res = MagicMock()
    mock_fetch.return_value = mock_res
    mock_validate.return_value = {"status": "ok", "message": "alive"}
    
    res = verify_full_system.check_backend_health()
    assert res == {"status": "ok", "message": "alive"}
    captured = capsys.readouterr()
    assert "Backend is online" in captured.out

# ==========================================
# check_council_api のテスト
# ==========================================

@patch("verify_full_system.requests.post")
def test_fetch_council_session_success(mock_post):
    mock_res = MagicMock()
    mock_post.return_value = mock_res
    res = verify_full_system._fetch_council_session("test query")
    assert res == mock_res
    mock_post.assert_called_once_with("http://localhost:8000/api/council/session", params={"query": "test query"}, timeout=10)

@patch("verify_full_system.requests.post")
def test_fetch_council_session_failure(mock_post, capsys):
    import requests
    mock_post.side_effect = requests.exceptions.RequestException("Timeout")
    with pytest.raises(SystemExit):
        verify_full_system._fetch_council_session("test query")
    captured = capsys.readouterr()
    assert "Council API Error: Network or timeout error: Timeout" in captured.out

def test_validate_council_response_data_success():
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": ["agent1: hello"],
        "synthesis": {"proposal": "stability proposal"}
    }
    session_id, debate_flow, proposal = verify_full_system._validate_council_response_data(mock_res)
    assert session_id == "session-123"
    assert debate_flow == ["agent1: hello"]
    assert proposal == "stability proposal"

def test_validate_council_response_data_non_200(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 400
    mock_res.text = "Bad Request"
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API returned 400: Bad Request" in captured.out

def test_validate_council_response_data_invalid_json(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.side_effect = ValueError("JSON error")
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API Error: Invalid JSON response: JSON error" in captured.out

def test_validate_council_response_data_missing_session_id(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "debate_flow": ["agent1: hello"],
        "synthesis": {"proposal": "stability proposal"}
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "No session_id returned" in captured.out

def test_validate_council_response_data_empty_debate_flow(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": [],
        "synthesis": {"proposal": "stability proposal"}
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "No debate_flow returned (Agents are silent)" in captured.out

def test_validate_council_response_data_missing_synthesis(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": ["agent1: hello"]
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "No synthesis returned (Nexus failed)" in captured.out

def test_validate_council_response_data_missing_proposal(capsys):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": ["agent1: hello"],
        "synthesis": {"other_key": "val"}
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API Error: synthesis is missing proposal key" in captured.out

@patch("verify_full_system._fetch_council_session")
@patch("verify_full_system._validate_council_response_data")
def test_check_council_api_success(mock_validate, mock_fetch, capsys):
    mock_fetch.return_value = MagicMock()
    mock_validate.return_value = ("session-123", ["agent1: hello"], "detailed proposal text")
    res = verify_full_system.check_council_api()
    assert res == "session-123"
    captured = capsys.readouterr()
    assert "Council Session session-123 successful" in captured.out

# ==========================================
# check_frontend_integrity のテスト
# ==========================================

@patch("verify_full_system.os.path.exists")
def test_verify_required_files_exist_success(mock_exists, capsys):
    mock_exists.return_value = True
    verify_full_system._verify_required_files_exist("/front", ["file1.js"])
    captured = capsys.readouterr()
    assert "Found file1.js" in captured.out

@patch("verify_full_system.os.path.exists")
def test_verify_required_files_exist_missing(mock_exists, capsys):
    mock_exists.return_value = False
    with pytest.raises(SystemExit):
        verify_full_system._verify_required_files_exist("/front", ["file1.js"])
    captured = capsys.readouterr()
    assert "Missing critical frontend file: file1.js" in captured.out

@patch("verify_full_system.open", new_callable=mock_open, read_data="body { font-family: 'Noto Sans JP'; } :root { --bg-primary: #f5f5f7; }")
def test_verify_css_styles_success(mock_file, capsys):
    verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "App.css contains 'Noto Sans JP'" in captured.out
    assert "App.css contains Light Theme variables" in captured.out

@patch("verify_full_system.open")
def test_verify_css_styles_open_error(mock_open_func, capsys):
    mock_open_func.side_effect = IOError("Permission denied")
    with pytest.raises(SystemExit):
        verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "Could not read App.css: Permission denied" in captured.out

@patch("verify_full_system.open", new_callable=mock_open, read_data="body { font-family: 'Arial'; }")
def test_verify_css_styles_missing_font(mock_file, capsys):
    with pytest.raises(SystemExit):
        verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "App.css missing 'Noto Sans JP' font definition." in captured.out

@patch("verify_full_system.open", new_callable=mock_open, read_data="body { font-family: 'Noto Sans JP'; }")
def test_verify_css_styles_missing_theme(mock_file, capsys):
    with pytest.raises(SystemExit):
        verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "App.css missing Light Theme variables." in captured.out

@patch("verify_full_system._verify_required_files_exist")
@patch("verify_full_system._verify_css_styles")
def test_check_frontend_integrity_success(mock_css, mock_files):
    verify_full_system.check_frontend_integrity()
    mock_files.assert_called_once()
    mock_css.assert_called_once()

# ==========================================
# main 関数のテスト
# ==========================================

@patch("verify_full_system.requests.get")
@patch("verify_full_system.requests.post")
@patch("verify_full_system.os.path.exists")
@patch("verify_full_system.open", new_callable=mock_open, read_data="body { font-family: 'Noto Sans JP'; } :root { --bg-primary: #f5f5f7; }")
def test_main_execution(mock_open_func, mock_exists, mock_post, mock_get, capsys):
    # requests.get の正常系レスポンス
    mock_res_get = MagicMock()
    mock_res_get.status_code = 200
    mock_res_get.json.return_value = {"status": "ok", "message": "alive"}
    mock_get.return_value = mock_res_get

    # requests.post の正常系レスポンス
    mock_res_post = MagicMock()
    mock_res_post.status_code = 200
    mock_res_post.json.return_value = {
        "session_id": "session-main",
        "debate_flow": ["agent1: synthesis test"],
        "synthesis": {"proposal": "Nexus proposal test for system check."}
    }
    mock_post.return_value = mock_res_post

    # os.path.exists の正常系挙動
    mock_exists.return_value = True

    # main関数を直接実行する
    verify_full_system.main()
    
    # 呼び出し確認
    mock_get.assert_called_once_with("http://localhost:8000/api/status", timeout=10)
    mock_post.assert_called_once()
    assert mock_exists.call_count == 5
    
    captured = capsys.readouterr()
    assert "Starting Mirai Gikai E2E Verification..." in captured.out
    assert "Backend is online" in captured.out
    assert "Council Session session-main successful." in captured.out
    assert "Found src/App.jsx" in captured.out
    assert "ALL SYSTEMS GO. STARTING UI TEST VIA BROWSER AGENT..." in captured.out

# ==========================================
# その他の追加テスト
# ==========================================

def test_environment_variable_override(monkeypatch):
    monkeypatch.setenv("API_BASE", "http://test-backend:9000")
    monkeypatch.setenv("FRONTEND_PATH", "/test/frontend/path")
    
    import importlib
    importlib.reload(verify_full_system)
    
    assert verify_full_system.API_BASE == "http://test-backend:9000"
    assert verify_full_system.FRONTEND_PATH == "/test/frontend/path"
    
    monkeypatch.delenv("API_BASE", raising=False)
    monkeypatch.delenv("FRONTEND_PATH", raising=False)
    importlib.reload(verify_full_system)

def test_default_frontend_path_dynamic(monkeypatch):
    monkeypatch.delenv("FRONTEND_PATH", raising=False)
    
    import importlib
    importlib.reload(verify_full_system)
    
    expected_path = os.path.abspath(os.path.join(os.path.dirname(verify_full_system.__file__), "..", "frontend"))
    assert verify_full_system.FRONTEND_PATH == expected_path


def test_parse_and_validate_status_response_non_dict(capsys):
    """_parse_and_validate_status_response の入力が辞書型以外（リスト型など）で sys.exit(1) となることを確認"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = ["status", "ok"]
    with pytest.raises(SystemExit):
        verify_full_system._parse_and_validate_status_response(mock_res)
    captured = capsys.readouterr()
    assert "Backend returned non-dict status response: list" in captured.out

def test_validate_council_response_data_non_dict(capsys):
    """_validate_council_response_data の json 戻り値が辞書型以外の場合に sys.exit(1) となることを確認"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = ["session_id", "debate_flow", "synthesis"]
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API returned non-dict response: list" in captured.out

def test_validate_council_response_data_synthesis_non_dict(capsys):
    """_validate_council_response_data の synthesis が辞書型以外の場合に sys.exit(1) となることを確認"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": ["agent1: hello"],
        "synthesis": "invalid_synthesis_format_string"
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API Error: synthesis is not a dict: str" in captured.out

@patch("verify_full_system.open")
def test_verify_css_styles_unicode_decode_error(mock_open_func, capsys):
    """App.css 読み込み時に UnicodeDecodeError が発生した際に sys.exit(1) となることを確認"""
    mock_open_func.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    with pytest.raises(SystemExit):
        verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "Could not read App.css:" in captured.out

@patch("verify_full_system.open")
def test_verify_css_styles_file_not_found_error(mock_open_func, capsys):
    """App.css が見つからない場合 (FileNotFoundError) に sys.exit(1) となることを確認"""
    mock_open_func.side_effect = FileNotFoundError("[Errno 2] No such file or directory")
    with pytest.raises(SystemExit):
        verify_full_system._verify_css_styles("/front")
    captured = capsys.readouterr()
    assert "Could not read App.css:" in captured.out

def test_parse_and_validate_status_response_none(capsys):
    """_parse_and_validate_status_response の引数が None の場合に sys.exit(1) となることを確認"""
    with pytest.raises(SystemExit):
        verify_full_system._parse_and_validate_status_response(None)
    captured = capsys.readouterr()
    assert "Could not connect to backend: Response is None" in captured.out

def test_validate_council_response_data_none(capsys):
    """_validate_council_response_data の引数が None の場合に sys.exit(1) となることを確認"""
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(None)
    captured = capsys.readouterr()
    assert "Council API Error: Response is None" in captured.out

# ==========================================
# 手順3のための追加テスト
# ==========================================

@patch("verify_full_system.requests.get")
def test_main_execution_failure(mock_get, capsys):
    """main関数実行時、バックエンド接続エラーで即座にSystemExitとなることのテスト"""
    import requests
    mock_get.side_effect = requests.exceptions.RequestException("Backend Offline")
    with pytest.raises(SystemExit) as excinfo:
        verify_full_system.main()
    
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Could not connect to backend: Connection error:" in captured.out

def test_validate_council_response_data_proposal_non_string(capsys):
    """_validate_council_response_data の synthesis['proposal'] が文字列でない場合に sys.exit(1) となることを確認"""
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "session_id": "session-123",
        "debate_flow": ["agent1: hello"],
        "synthesis": {"proposal": 12345}  # 非文字列（int）
    }
    with pytest.raises(SystemExit):
        verify_full_system._validate_council_response_data(mock_res)
    captured = capsys.readouterr()
    assert "Council API Error: proposal is not a string: int" in captured.out
