from unittest.mock import MagicMock, patch
import pytest
import sys
from backend.agents.orchestration.mark_tasks_001 import main

def test_main_with_mocked_hub():
    # OrchestrationHub のモックを作成
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}

    # main 関数を呼び出す
    main(
        hub=mock_hub,
        conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
        task_id="T-batch_a1eb03-thumbnail-001"
    )

    # 各メソッドが期待通り呼び出されたか検証
    mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_a1eb03-thumbnail-001",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": []
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

def test_main_integration_with_patch():
    # OrchestrationHub クラス自体をモック化
    with patch("backend.agents.orchestration.mark_tasks_001.OrchestrationHub") as mock_class:
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        mock_class.return_value = mock_hub

        # 環境変数を設定して main を呼び出す
        with patch.dict("os.environ", {
            "FLASH_CONVERSATION_ID": "a9736a64-a242-485f-942e-bf8476d21fa6",
            "FLASH_TASK_ID": "T-batch_a1eb03-thumbnail-001"
        }):
            main()

        # OrchestrationHub がインスタンス化されたことを検証
        mock_class.assert_called_once()
        
        # 各メソッドが呼び出されたことを検証
        mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()

def test_main_with_custom_arguments():
    # カスタム引数の動作確認
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}
    
    custom_conv_id = "test-conv-id"
    custom_task_id = "test-task-id"
    custom_status = "fail"
    custom_message = "テスト用カスタムメッセージ"
    custom_files = ["test_file_1.py"]

    main(
        hub=mock_hub,
        conversation_id=custom_conv_id,
        task_id=custom_task_id,
        status_str=custom_status,
        message=custom_message,
        changed_files=custom_files
    )

    mock_hub.register_flash_conversation_id.assert_called_once_with(custom_conv_id)
    mock_hub.mark_task_done.assert_called_once_with(
        custom_task_id,
        custom_status,
        {
            "message": custom_message,
            "changed_files": custom_files
        }
    )

def test_main_with_exception_handling():
    # 例外ハンドリングの確認 (ValueError が発生した場合)
    mock_hub = MagicMock()
    mock_hub.register_flash_conversation_id.side_effect = ValueError("Mock Value Error")

    with patch("backend.agents.orchestration.mark_tasks_001.logger") as mock_logger:
        result = main(
            hub=mock_hub,
            conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
            task_id="T-batch_a1eb03-thumbnail-001"
        )
        
        # 戻り値が 1 であること
        assert result == 1
        # logger.exception が期待されるエラーメッセージとともに呼ばれていること
        mock_logger.exception.assert_called_once()
        assert "エラー: 実行中に想定外のエラーが発生しました: Mock Value Error" in mock_logger.exception.call_args[0][0]


def test_main_with_system_exception_handling():
    # 予期せぬシステム例外の確認 (RuntimeError が発生した場合)
    mock_hub = MagicMock()
    mock_hub.register_flash_conversation_id.side_effect = RuntimeError("Mock Runtime Error")

    with patch("backend.agents.orchestration.mark_tasks_001.logger") as mock_logger:
        result = main(
            hub=mock_hub,
            conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
            task_id="T-batch_a1eb03-thumbnail-001"
        )
        
        assert result == 1
        mock_logger.exception.assert_called_once()
        assert "エラー: 実行中に想定外のエラーが発生しました: Mock Runtime Error" in mock_logger.exception.call_args[0][0]

def test_main_fallback_to_env_vars():
    # 環境変数からのフォールバックを検証
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}

    env_conversation_id = "env-conv-111"
    env_task_id = "env-task-222"

    with patch.dict("os.environ", {
        "FLASH_CONVERSATION_ID": env_conversation_id,
        "FLASH_TASK_ID": env_task_id
    }):
        result = main(hub=mock_hub, conversation_id=None, task_id=None)

    assert result == 0
    mock_hub.register_flash_conversation_id.assert_called_once_with(env_conversation_id)
    mock_hub.mark_task_done.assert_called_once_with(
        env_task_id,
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": []
        }
    )

def test_main_missing_parameters():
    # 必須パラメータがない場合のエラー終了を検証
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.mark_tasks_001.logger") as mock_logger:
        result = main(hub=mock_hub, conversation_id=None, task_id=None)
        assert result == 1
        mock_logger.error.assert_called_once()
        assert "エラー: conversation_id が指定されておらず" in mock_logger.error.call_args[0][0]

def test_main_invalid_status():
    # 無効なステータスによるエラー終了を検証
    mock_hub = MagicMock()
    
    with patch("backend.agents.orchestration.mark_tasks_001.logger") as mock_logger:
        result = main(
            hub=mock_hub,
            conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
            task_id="T-batch_a1eb03-thumbnail-001",
            status_str="invalid_status"
        )
        assert result == 1
        mock_logger.error.assert_called_once()
        assert "エラー: 無効なステータス 'invalid_status' が指定されました。" in mock_logger.error.call_args[0][0]

def test_main_status_normalization():
    # ステータスの正規化（大文字・小文字、トリム）を検証
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}

    result = main(
        hub=mock_hub,
        conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
        task_id="T-batch_a1eb03-thumbnail-001",
        status_str="  PASS  "
    )
    assert result == 0
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_a1eb03-thumbnail-001",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": []
        }
    )

def test_main_changed_files_parsing():
    # 変更されたファイルリストのカンマ区切りおよびトリム処理を検証
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}

    result = main(
        hub=mock_hub,
        conversation_id="a9736a64-a242-485f-942e-bf8476d21fa6",
        task_id="T-batch_a1eb03-thumbnail-001",
        changed_files=["file1.py,file2.py", "  file3.py  ", "", "file4.py , file5.py"]
    )
    assert result == 0
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_a1eb03-thumbnail-001",
        "pass",
        {
            "message": "Task marked done via mark_tasks_001",
            "changed_files": ["file1.py", "file2.py", "file3.py", "file4.py", "file5.py"]
        }
    )
