import sys
import runpy
from unittest.mock import MagicMock, patch
import pytest

@pytest.fixture(autouse=True)
def clean_generate_status():
    # scratch.generate_status だけでなく、親パッケージ scratch も sys.modules から削除して
    # パッケージ属性のキャッシュによるモジュールオブジェクトの不一致を完全に防ぐ
    sys.modules.pop("scratch.generate_status", None)
    sys.modules.pop("scratch", None)
    from scratch import generate_status
    return generate_status

def test_main_default(clean_generate_status):
    # 引数なしの場合
    # hub.generate_flash_status() が呼ばれ、戻り値が print されることを確認
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status OK"}
        
        clean_generate_status.main()
        
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("2c563fff-a220-4ba2-8e1f-2f05e4b5a090")
        mock_hub_instance.generate_flash_status.assert_called_once()
        mock_print.assert_called_with("Status OK")

def test_main_default_no_formatted(clean_generate_status):
    # formatted キーがない場合
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.return_value = {}
        
        clean_generate_status.main()
        
        mock_print.assert_called_with("No formatted status available.")

def test_main_heartbeat(clean_generate_status):
    # 引数 "heartbeat" の場合
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "heartbeat"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        
        clean_generate_status.main()
        
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_print.assert_called_with("Heartbeat updated.")

def test_main_end_default_reason(clean_generate_status):
    # 引数 "end" で理由指定なしの場合
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "end"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        
        clean_generate_status.main()
        
        mock_hub_instance.flash_session_end.assert_called_once_with("ミッション完遂")
        mock_print.assert_called_with("Session ended: ミッション完遂")

def test_main_end_custom_reason(clean_generate_status):
    # 引数 "end" で理由指定ありの場合
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "end", "カスタム理由"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        
        clean_generate_status.main()
        
        mock_hub_instance.flash_session_end.assert_called_once_with("カスタム理由")
        mock_print.assert_called_with("Session ended: カスタム理由")

def test_script_execution(clean_generate_status):
    # __name__ == "__main__" ブロックの実行カバー
    # runpy.run_module を使い、モジュールとして実行することでカバレッジのズレを防ぐ
    with patch("backend.agents.orchestration.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status OK"}
        
        # 警告 'scratch.generate_status' found in sys.modules を回避するために pop する
        sys.modules.pop("scratch.generate_status", None)
        sys.modules.pop("scratch", None)
        
        # モジュールとして実行
        runpy.run_module("scratch.generate_status", run_name="__main__")
        
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("2c563fff-a220-4ba2-8e1f-2f05e4b5a090")
        mock_hub_instance.generate_flash_status.assert_called_once()
        mock_print.assert_called_with("Status OK")

def test_main_invalid_command_argument(clean_generate_status):
    # 引数に想定外のものが指定された場合、default挙動(else句)になることを確認
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "invalid_action"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.return_value = {"formatted": "Status OK"}
        
        clean_generate_status.main()
        
        mock_hub_instance.generate_flash_status.assert_called_once()
        mock_print.assert_called_with("Status OK")

def test_main_hub_heartbeat_exception(clean_generate_status):
    # heartbeat処理中に例外が発生した場合の挙動を検証
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "heartbeat"]):
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.flash_update_heartbeat.side_effect = ValueError("Heartbeat failed")
        
        with pytest.raises(SystemExit) as exc_info:
            clean_generate_status.main()
        assert exc_info.value.code == 1

def test_main_hub_end_exception(clean_generate_status):
    # end処理中に例外が発生した場合の挙動を検証
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "end"]):
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.flash_session_end.side_effect = RuntimeError("Failed to end session")
        
        with pytest.raises(SystemExit) as exc_info:
            clean_generate_status.main()
        assert exc_info.value.code == 1

def test_main_hub_status_exception(clean_generate_status):
    # status取得中に例外が発生した場合の挙動を検証
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py"]):
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.side_effect = ConnectionError("Network down")
        
        with pytest.raises(SystemExit) as exc_info:
            clean_generate_status.main()
        assert exc_info.value.code == 1

def test_main_end_extra_arguments(clean_generate_status):
    # 引数が余分にある場合（sys.argvの長さが3より大きい）でも、2番目の要素のみがreasonに渡されることを検証
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("sys.argv", ["generate_status.py", "end", "reason_arg", "extra_arg"]),          patch("builtins.print") as mock_print:
        
        mock_hub_instance = MockHub.return_value
        
        clean_generate_status.main()
        
        mock_hub_instance.flash_session_end.assert_called_once_with("reason_arg")
        mock_print.assert_called_with("Session ended: reason_arg")

def test_main_exception_handling_and_debt_registration(clean_generate_status):
    # OrchestrationHubの処理中に例外が発生した場合のハンドリングと技術負債登録を検証
    with patch("scratch.generate_status.OrchestrationHub") as MockHub,          patch("scratch.generate_status.TechnicalDebtStore") as MockDebtStore,          patch("sys.argv", ["generate_status.py"]),          patch("sys.stderr") as mock_stderr:
        
        mock_hub_instance = MockHub.return_value
        mock_hub_instance.generate_flash_status.side_effect = RuntimeError("Hub processing error")
        
        mock_debt_store_instance = MockDebtStore.return_value
        
        with pytest.raises(SystemExit) as exc_info:
            clean_generate_status.main()
            
        assert exc_info.value.code == 1
        
        # stderr にエラーメッセージが出力されたことの確認
        mock_stderr.write.assert_any_call("Error in generate_status.py: Hub processing error")
        
        # 技術負債が登録されたことの確認
        mock_debt_store_instance.register_debt.assert_called_once()
        call_args = mock_debt_store_instance.register_debt.call_args[1]
        assert call_args["category"] == "MINOR_INFRA"
        assert call_args["file_path"] == "tests/scratch/generate_status.py"
        assert "except Exception as e:" in call_args["pattern"]
        assert "Hub processing error" in call_args["notes"]
