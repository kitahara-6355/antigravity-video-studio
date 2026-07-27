import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_001

def test_main_default_arguments():
    # 引数が指定されていない場合、環境変数から値を取得し、デフォルト値（messageやchanged_files）で呼び出されることを検証
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # sys.argvを空（スクリプト名のみ）にする
    test_args = ["mark_tasks_001.py"]
    
    with patch.dict("os.environ", {
        "FLASH_CONVERSATION_ID": "a9736a64-a242-485f-942e-bf8476d21fa6",
        "FLASH_TASK_ID": "T-batch_a1eb03-thumbnail-001"
    }):
        with patch.object(sys, "argv", test_args):
            with patch("backend.agents.orchestration.mark_tasks_001.OrchestrationHub", return_value=mock_hub_instance):
                result = mark_tasks_001.main()
                assert result == 0
            
    # デフォルト値の検証
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_a1eb03-thumbnail-001",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": []
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()

def test_main_custom_arguments():
    # カスタムコマンドライン引数が正しくパースされ、OrchestrationHubへ渡されることを検証
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    test_args = [
        "mark_tasks_001.py",
        "--conversation-id", "conv-custom-123",
        "--task-id", "T-task-custom-456",
        "--status", "fail",
        "--message", "カスタムエラーメッセージ",
        "--changed-files", "file1.py", "file2.py"
    ]
    
    with patch.object(sys, "argv", test_args):
        with patch("backend.agents.orchestration.mark_tasks_001.OrchestrationHub", return_value=mock_hub_instance):
            # argparseによるパース後に main() を呼び出す動作を模倣
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument("--conversation-id", "-c", type=str)
            parser.add_argument("--task-id", "-t", type=str)
            parser.add_argument("--status", "-s", type=str)
            parser.add_argument("--message", "-m", type=str)
            parser.add_argument("--changed-files", "-f", nargs="*")
            
            args = parser.parse_args(test_args[1:])
            
            result = mark_tasks_001.main(
                conversation_id=args.conversation_id,
                task_id=args.task_id,
                status_str=args.status,
                message=args.message,
                changed_files=args.changed_files
            )
            assert result == 0
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-custom-123")
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-task-custom-456",
        "fail",
        {
            "message": "カスタムエラーメッセージ",
            "changed_files": ["file1.py", "file2.py"]
        }
    )

def test_script_execution_via_main():
    # __main__ ブロックでのコマンドライン引数パースと実行を検証
    import runpy
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    test_args = [
        "mark_tasks_001.py",
        "-c", "conv-main-789",
        "-t", "T-task-main-000",
        "-s", "pass",
        "-m", "メインブロックテスト",
        "-f", "file_a.py"
    ]
    
    with patch.object(sys, "argv", test_args):
        # backend.agents.orchestration.OrchestrationHub 大本をパッチする
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            # runpyを使ってスクリプト全体を実行する。sys.exit()によりSystemExitが発生することを検証
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_path("backend/agents/orchestration/mark_tasks_001.py", run_name="__main__")
            assert exc_info.value.code == 0
            
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("conv-main-789")
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-task-main-000",
        "pass",
        {
            "message": "メインブロックテスト",
            "changed_files": ["file_a.py"]
        }
    )

def test_main_changed_files_as_string():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # 1. 単一のファイルパス文字列が渡された場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        changed_files="single_file.py",
        hub=mock_hub_instance
    )
    assert result == 0
    
    mock_hub_instance.mark_task_done.assert_called_with(
        "T-task-str-456",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["single_file.py"]
        }
    )

    # 2. カンマ区切りの文字列が渡された場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        changed_files="file1.py, file2.py",
        hub=mock_hub_instance
    )
    assert result == 0
    
    mock_hub_instance.mark_task_done.assert_called_with(
        "T-task-str-456",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["file1.py", "file2.py"]
        }
    )

def test_main_invalid_status():
    mock_hub_instance = MagicMock()
    
    # 無効なステータス
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        status_str="invalid_status",
        hub=mock_hub_instance
    )
    assert result == 1
    mock_hub_instance.mark_task_done.assert_not_called()

def test_main_missing_identifiers():
    mock_hub_instance = MagicMock()
    
    with patch.dict("os.environ", {}, clear=True):
        # conversation_id が欠損
        result = mark_tasks_001.main(
            conversation_id=None,
            task_id="T-task-123",
            hub=mock_hub_instance
        )
        assert result == 1
        
        # task_id が欠損
        result = mark_tasks_001.main(
            conversation_id="conv-123",
            task_id=None,
            hub=mock_hub_instance
        )
        assert result == 1

def test_main_exception_handling():
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = Exception("Hub error")
    
    result = mark_tasks_001.main(
        conversation_id="conv-err-123",
        task_id="T-task-err-456",
        hub=mock_hub_instance
    )
    assert result == 1

def test_main_opus_quota_exception_handling():
    from backend.agents.orchestration.hub_common import OpusQuotaExceededException
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = OpusQuotaExceededException("Quota exceeded")
    
    result = mark_tasks_001.main(
        conversation_id="conv-quota-123",
        task_id="T-task-quota-456",
        hub=mock_hub_instance
    )
    assert result == 1

def test_main_changed_files_mixed_and_empty():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # 混在する入力 (カンマ区切り, 空文字, 通常文字列)
    mixed_input = ["file1.py, file2.py", "", "file3.py", "  ,  "]
    
    result = mark_tasks_001.main(
        conversation_id="conv-mixed-123",
        task_id="T-task-mixed-456",
        changed_files=mixed_input,
        hub=mock_hub_instance
    )
    assert result == 0
    
    mock_hub_instance.mark_task_done.assert_called_with(
        "T-task-mixed-456",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["file1.py", "file2.py", "file3.py"]
        }
    )

def test_main_invalid_status_types():
    mock_hub_instance = MagicMock()
    
    # status_str が None の場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        status_str=None,
        hub=mock_hub_instance
    )
    assert result == 1
    mock_hub_instance.mark_task_done.assert_not_called()

    # status_str が 文字列以外（int型）の場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        status_str=123,
        hub=mock_hub_instance
    )
    assert result == 1
    mock_hub_instance.mark_task_done.assert_not_called()

def test_main_changed_files_robustness():
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    # 1. changed_files にイテラブルでないオブジェクト（数値など）が渡された場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        changed_files=999,
        hub=mock_hub_instance
    )
    assert result == 0
    mock_hub_instance.mark_task_done.assert_called_with(
        "T-task-str-456",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["999"]
        }
    )

    # 2. changed_files のリスト内に文字列以外の要素が混入している場合
    result = mark_tasks_001.main(
        conversation_id="conv-str-123",
        task_id="T-task-str-456",
        changed_files=["file1.py", 100, None, "file2.py"],
        hub=mock_hub_instance
    )
    assert result == 0
    mock_hub_instance.mark_task_done.assert_called_with(
        "T-task-str-456",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["file1.py", "100", "None", "file2.py"]
        }
    )

def test_main_exception_logging_content():
    # 例外発生時のログ出力に例外メッセージが含まれていることを検証
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = Exception("特殊なテスト用エラーメッセージ")
    
    with patch("backend.agents.orchestration.mark_tasks_001.logger") as mock_logger:
        result = mark_tasks_001.main(
            conversation_id="conv-err-123",
            task_id="T-task-err-456",
            hub=mock_hub_instance
        )
        assert result == 1
        # logger.exception が呼ばれ、その中にエラーメッセージが含まれることを検証
        mock_logger.exception.assert_called_once()
        log_arg = mock_logger.exception.call_args[0][0]
        assert "特殊なテスト用エラーメッセージ" in log_arg
