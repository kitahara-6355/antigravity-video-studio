import sys
import os
from unittest.mock import MagicMock, patch
import json
import pytest
import runpy

# テスト対象がモックをロードする前にインポートできるようにパスを設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

@pytest.fixture(autouse=True)
def clean_modules():
    """
    テストごとにテスト対象モジュールを sys.modules から削除して、
    インポート時（トップレベル）の処理が正しく走りカバレッジが計測されるようにします。
    """
    yield
    sys.modules.pop('backend.agents.orchestration.mark_and_submit_batch4', None)

@patch('backend.agents.orchestration.OrchestrationHub')
def test_main_function(mock_hub_class, capsys):
    """
    main() 関数の呼び出しにおいて、OrchestrationHub のメソッドが期待通りに呼び出され、
    標準出力に正しい文字列が出力されることをテストします。
    """
    # モックインスタンスの設定
    mock_hub_instance = MagicMock()
    mock_hub_class.return_value = mock_hub_instance
    mock_hub_instance.generate_flash_status.return_value = {"status": "success", "tasks": []}

    # テスト対象のインポートと実行
    from backend.agents.orchestration.mark_and_submit_batch4 import main
    main()

    # OrchestrationHub の各メソッドの呼び出し検証
    mock_hub_class.assert_called_once()
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    mock_hub_instance.flash_update_heartbeat.assert_called_once()
    
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "T-batch_881c02-thumbnail-000",
        "pass",
        {
            "message": "branding/analytics_manager.py のサムネイル処理改善と品質検証・テスト追加。",
            "changed_files": [
                "backend/branding/analytics_manager.py",
                "backend/tests/test_analytics_manager.py",
                "backend/agents/memory/technical_debt_index.json"
            ]
        }
    )

    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_881c02",
        {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
    )

    mock_hub_instance.generate_flash_status.assert_called_once()

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS:" in captured.out
    
    # JSON 形式のステータスが出力されているか検証
    status_line = [line for line in captured.out.splitlines() if line.startswith("FLASH_STATUS:")][0]
    json_part = status_line.replace("FLASH_STATUS:", "")
    parsed_status = json.loads(json_part)
    assert parsed_status == {"status": "success", "tasks": []}


@patch('backend.agents.orchestration.OrchestrationHub')
def test_script_execution(mock_hub_class, capsys):
    """
    runpy を使用して __name__ == "__main__" のブロックを含めてスクリプトを実行し、
    カバレッジを 100% にします。
    """
    # 確実にモジュールを新規ロードさせるために pop
    sys.modules.pop('backend.agents.orchestration.mark_and_submit_batch4', None)

    mock_hub_instance = MagicMock()
    mock_hub_class.return_value = mock_hub_instance
    mock_hub_instance.generate_flash_status.return_value = {"status": "running"}

    # runpy を用いてモジュールを実行
    module_path = "backend.agents.orchestration.mark_and_submit_batch4"
    runpy.run_module(module_path, run_name="__main__")

    # 呼び出しが正常に行われたことを検証
    mock_hub_class.assert_called_once()
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
    
    captured = capsys.readouterr()
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS:" in captured.out


@patch('backend.agents.orchestration.OrchestrationHub')
def test_main_function_exception(mock_hub_class, capsys):
    """
    OrchestrationHub の登録処理で例外が発生した際、
    エラーメッセージが標準エラー出力に出力され、sys.exit(1) で終了することをテストします。
    """
    # 確実にモジュールを新規ロードさせるために pop
    sys.modules.pop('backend.agents.orchestration.mark_and_submit_batch4', None)

    mock_hub_instance = MagicMock()
    mock_hub_class.return_value = mock_hub_instance
    mock_hub_instance.register_flash_conversation_id.side_effect = RuntimeError("Mock DB Error")

    from backend.agents.orchestration.mark_and_submit_batch4 import main
    with pytest.raises(SystemExit) as excinfo:
        main()
    
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error in mark_and_submit_batch4: Mock DB Error" in captured.err
