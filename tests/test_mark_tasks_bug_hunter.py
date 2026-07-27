import sys
import pytest
from unittest.mock import MagicMock, patch
from backend.agents.orchestration.mark_tasks_bug_hunter import main

def test_main_success():
    """main()が正常に動作し、OrchestrationHubのメソッドが期待通り呼び出されることを検証。"""
    with patch('backend.agents.orchestration.mark_tasks_bug_hunter.OrchestrationHub') as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        mock_hub_class.return_value = mock_hub
        
        # mainの実行
        main()
        
        # 期待される呼び出しの検証
        mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_a1eb03-bug_hunter-000",
            "pass",
            {
                "message": "settings_manager.py の例外処理改善（ベア except からの TDR 登録連携）。",
                "changed_files": [
                    "backend/settings_manager.py",
                    "backend/tests/test_settings_manager.py",
                    "backend/agents/memory/technical_debt_index.json"
                ]
            }
        )
        mock_hub.generate_flash_status.assert_called_once()

def test_main_failure_and_debt_registration():
    """main()で例外が発生した際に、技術負債が登録され、sys.exit(1)で終了することを検証。"""
    with patch('backend.agents.orchestration.mark_tasks_bug_hunter.OrchestrationHub') as mock_hub_class,          patch('backend.agents.memory.technical_debt.TechnicalDebtStore') as mock_debt_store_class:
         
        mock_hub = MagicMock()
        mock_hub.register_flash_conversation_id.side_effect = ValueError("Test Hub Connection Failure")
        mock_hub_class.return_value = mock_hub
        
        mock_store = MagicMock()
        mock_debt_store_class.return_value = mock_store
        
        # 例外発生時にsys.exit(1)で終了することを確認
        with pytest.raises(SystemExit) as excinfo:
            main()
            
        assert excinfo.value.code == 1
        
        # register_debtが呼び出されたことを検証
        mock_store.register_debt.assert_called_once()
        call_kwargs = mock_store.register_debt.call_args.kwargs
        assert call_kwargs["category"] == "MINOR_INFRA"
        assert "mark_tasks_bug_hunter.py" in call_kwargs["file_path"]
        assert "Test Hub Connection Failure" in call_kwargs["notes"]


def test_main_failure_specific_exceptions():
    """ValueErrorなどの特定の例外が発生した際にも捕捉され、技術負債登録が実行されることを検証。"""
    with patch('backend.agents.orchestration.mark_tasks_bug_hunter.OrchestrationHub') as mock_hub_class, \
         patch('backend.agents.memory.technical_debt.TechnicalDebtStore') as mock_debt_store_class:
         
        mock_hub = MagicMock()
        mock_hub.register_flash_conversation_id.side_effect = ValueError("Test Specific ValueError")
        mock_hub_class.return_value = mock_hub
        
        mock_store = MagicMock()
        mock_debt_store_class.return_value = mock_store
        
        with pytest.raises(SystemExit) as excinfo:
            main()
            
        assert excinfo.value.code == 1
        mock_store.register_debt.assert_called_once()
        call_kwargs = mock_store.register_debt.call_args.kwargs
        assert "Test Specific ValueError" in call_kwargs["notes"]

def test_main_debt_registration_failure(capsys):
    """技術負債の登録処理自体でOSError等が発生した際に、インナーのexceptで捕捉され、エラーメッセージが出力されることを検証。"""
    with patch('backend.agents.orchestration.mark_tasks_bug_hunter.OrchestrationHub') as mock_hub_class, \
         patch('backend.agents.memory.technical_debt.TechnicalDebtStore') as mock_debt_store_class:
         
        mock_hub = MagicMock()
        mock_hub.register_flash_conversation_id.side_effect = ValueError("Initial Failure")
        mock_hub_class.return_value = mock_hub
        
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = OSError("Database Write Error")
        mock_debt_store_class.return_value = mock_store
        
        with pytest.raises(SystemExit) as excinfo:
            main()
            
        assert excinfo.value.code == 1
        
        # 標準エラー出力に期待するログが出力されているかを検証
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Database Write Error" in captured.err
