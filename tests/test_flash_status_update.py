import sys
import os
import pytest
import runpy
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SCRIPT_PATH = os.path.join(PROJECT_ROOT, "backend/agents/orchestration/flash_status_update.py")

@pytest.fixture
def mock_hub():
    hub = MagicMock()
    # デフォルトの挙動を設定
    hub.get_flash_session.return_value = {}
    hub.generate_flash_status.return_value = {"formatted": "Mocked Status Output"}
    return hub

def test_default_execution(mock_hub, capsys):
    """引数なし、環境変数なしのデフォルト実行テスト"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub) as mock_class:
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["flash_status_update.py"]):
                runpy.run_path(SCRIPT_PATH, run_name="__main__")
                
                mock_class.assert_called_once()
                mock_hub.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
                mock_hub.flash_update_heartbeat.assert_called_once()
                mock_hub.generate_flash_status.assert_called_once()
                
                captured = capsys.readouterr()
                assert "Mocked Status Output" in captured.out

def test_args_conversation_id(mock_hub):
    """コマンドライン引数で conversation-id を指定した場合"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("sys.argv", ["flash_status_update.py", "--conversation-id", "test-arg-id"]):
            runpy.run_path(SCRIPT_PATH, run_name="__main__")
            mock_hub.register_flash_conversation_id.assert_called_once_with("test-arg-id")

def test_env_conversation_id(mock_hub):
    """環境変数 FLASH_CONVERSATION_ID でIDを指定した場合"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch.dict(os.environ, {"FLASH_CONVERSATION_ID": "test-env-id"}):
            with patch("sys.argv", ["flash_status_update.py"]):
                runpy.run_path(SCRIPT_PATH, run_name="__main__")
                mock_hub.register_flash_conversation_id.assert_called_once_with("test-env-id")

def test_json_conversation_id(mock_hub):
    """既存のセッション情報からIDを取得できる場合"""
    mock_hub.get_flash_session.return_value = {"conversation_id": "test-json-id"}
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["flash_status_update.py"]):
                runpy.run_path(SCRIPT_PATH, run_name="__main__")
                mock_hub.register_flash_conversation_id.assert_called_once_with("test-json-id")

def test_heartbeat_only(mock_hub, capsys):
    """--heartbeat-only 指定時"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("sys.argv", ["flash_status_update.py", "--heartbeat-only"]):
            runpy.run_path(SCRIPT_PATH, run_name="__main__")
            mock_hub.flash_update_heartbeat.assert_called_once()
            mock_hub.generate_flash_status.assert_not_called()
            
            captured = capsys.readouterr()
            assert "Mocked Status Output" not in captured.out

def test_status_only(mock_hub, capsys):
    """--status-only 指定時"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("sys.argv", ["flash_status_update.py", "--status-only"]):
            runpy.run_path(SCRIPT_PATH, run_name="__main__")
            mock_hub.flash_update_heartbeat.assert_not_called()
            mock_hub.generate_flash_status.assert_called_once()
            
            captured = capsys.readouterr()
            assert "Mocked Status Output" in captured.out

def test_exception_handling_on_init(capsys):
    """初期化時に例外が発生した場合のハンドリング"""
    with patch("backend.agents.orchestration.OrchestrationHub", side_effect=OSError("Disk full or missing file")):
        with patch("sys.argv", ["flash_status_update.py"]):
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_path(SCRIPT_PATH, run_name="__main__")
            
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Error: Disk full or missing file" in captured.err

def test_exception_handling_on_status(mock_hub, capsys):
    """ステータス表示でキーエラーなどが発生した場合のハンドリング"""
    mock_hub.generate_flash_status.side_effect = KeyError("formatted key missing")
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("sys.argv", ["flash_status_update.py"]):
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_path(SCRIPT_PATH, run_name="__main__")
                
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Error: 'formatted key missing'" in captured.err

def test_direct_argv_passing(mock_hub):
    """main関数に引数を直接argvパラメータで渡した場合の動作検証"""
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        from backend.agents.orchestration.flash_status_update import main
        main(["--conversation-id", "direct-passed-id"])
        mock_hub.register_flash_conversation_id.assert_called_once_with("direct-passed-id")

def test_generate_status_returns_invalid_type(mock_hub, capsys):
    """generate_flash_status が辞書ではない不正な型を返した場合"""
    mock_hub.generate_flash_status.return_value = "Not A Dict Status"
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with pytest.raises(SystemExit) as exc_info:
            from backend.agents.orchestration.flash_status_update import main
            main([])
            
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Status dictionary is empty or missing 'formatted' key" in captured.err

def test_unexpected_exception_registration_in_tdr(mock_hub, capsys):
    """予期せぬ例外が発生した際、具体的な例外ルートを通り、TDR登録が行われること"""
    mock_hub.generate_flash_status.side_effect = TypeError("Unexpected Type Error")
    
    mock_store = MagicMock()
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store) as mock_store_class:
            from backend.agents.orchestration.flash_status_update import main
            with pytest.raises(SystemExit) as exc_info:
                main([])
                
            assert exc_info.value.code == 1
            mock_store_class.assert_called_once()
            mock_store.register_debt.assert_called_once()
            
            # TDRへの登録パラメータ検証
            args, kwargs = mock_store.register_debt.call_args
            assert kwargs.get("category") == "MINOR_INFRA"
            assert "flash_status_update.py" in kwargs.get("file_path")
            assert kwargs.get("pattern") == "except Exception as e:"
            
            captured = capsys.readouterr()
            assert "Unexpected Error: Unexpected Type Error" in captured.err


def test_zero_division_exception_handled_by_except_exception(mock_hub, capsys):
    """ZeroDivisionErrorのような予期せぬ例外が発生した際にも TDR 登録されて正常終了（SystemExit(1)）すること"""
    mock_hub.generate_flash_status.side_effect = ZeroDivisionError("division by zero")
    
    mock_store = MagicMock()
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store) as mock_store_class:
            from backend.agents.orchestration.flash_status_update import main
            with pytest.raises(SystemExit) as exc_info:
                main([])
                
            assert exc_info.value.code == 1
            mock_store_class.assert_called_once()
            mock_store.register_debt.assert_called_once()
            
            args, kwargs = mock_store.register_debt.call_args
            assert kwargs.get("pattern") == "except Exception as e:"
            assert "ZeroDivisionError" in kwargs.get("notes")
            
            captured = capsys.readouterr()
            assert "Unexpected Error: division by zero" in captured.err



def test_tdr_registration_raises_concrete_exception_ignored(mock_hub, capsys):
    """TDR登録時に具体的な捕捉対象例外（OSErrorなど）が発生しても、無視されてUnexpected Errorが出力され終了すること"""
    mock_hub.generate_flash_status.side_effect = TypeError("Unexpected Type Error")
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = OSError("Disk I/O Error during TDR registration")
        
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
            from backend.agents.orchestration.flash_status_update import main
            with pytest.raises(SystemExit) as exc_info:
                main([])
                
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Unexpected Error: Unexpected Type Error" in captured.err

def test_tdr_registration_raises_other_exception_propagated(mock_hub, capsys):
    """TDR登録時に例外が発生した場合でも、無視されて元の例外が出力されSystemExit(1)で終了すること"""
    mock_hub.generate_flash_status.side_effect = NameError("Unexpected Name Error")
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = RuntimeError("Uncaught TDR Error")
        
        with patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store):
            from backend.agents.orchestration.flash_status_update import main
            with pytest.raises(SystemExit) as exc_info:
                main([])
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Unexpected Error: Unexpected Name Error" in captured.err


def test_get_flash_session_exception_ignored(mock_hub):
    """get_flash_session が例外を投げた場合に無視され、デフォルトのIDが使われること"""
    mock_hub.get_flash_session.side_effect = OSError("Session file not found")
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with patch.dict(os.environ, {}, clear=True):
            from backend.agents.orchestration.flash_status_update import main
            main([])
            mock_hub.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")

def test_sys_path_not_polluted(capsys):
    """インポート時に sys.path が過剰に汚染されないことの検証"""
    import sys
    # 初期状態の sys.path コピー
    original_path = list(sys.path)
    
    # flash_status_update をインポートする
    if "backend.agents.orchestration.flash_status_update" in sys.modules:
        del sys.modules["backend.agents.orchestration.flash_status_update"]
    
    import backend.agents.orchestration.flash_status_update
    
    # 新しく追加されたパスを特定
    new_paths = [p for p in sys.path if p not in original_path]
    
    # backend ディレクトリが新しく追加されていないことの確認
    backend_path = os.path.abspath(os.path.join(PROJECT_ROOT, "backend"))
    assert backend_path not in new_paths
    
    # 復元
    sys.path = original_path

