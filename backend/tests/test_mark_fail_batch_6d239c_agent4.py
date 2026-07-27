"""
backend.agents.orchestration.mark_fail_batch_6d239c_agent4 のテストモジュール。
"""

import runpy
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# テスト対象がインポートできるように sys.path を設定
ROOT_PATH = str(Path(__file__).resolve().parents[2])
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)

# backend をインポートパスに追加
BACKEND_PATH = str(Path(__file__).resolve().parents[2] / "backend")
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

from backend.agents.orchestration.mark_fail_batch_6d239c_agent4 import (
    mark_timeout_failure,
    main,
    create_timeout_report_payload,
    parse_arguments,
    DEFAULT_TIMEOUT_TASK_ID,
    TIMEOUT_ERROR_MESSAGE,
    _normalize_changed_files,
    _report_failure_to_hub
)


def test_normalize_changed_files():
    """
    _normalize_changed_files が None を空リストに変換し、リストをそのまま返すことをテストする。
    """
    assert _normalize_changed_files(None) == []
    assert _normalize_changed_files([]) == []
    assert _normalize_changed_files(["file1.py"]) == ["file1.py"]


def test_report_failure_to_hub():
    """
    _report_failure_to_hub が OrchestrationHub の mark_task_done を正しく呼び出すことをテストする。
    """
    mock_hub = MagicMock()
    payload = {"error": "test"}
    _report_failure_to_hub(mock_hub, "task-123", payload)
    mock_hub.mark_task_done.assert_called_once_with("task-123", "fail", payload)


def test_create_timeout_report_payload():
    """
    create_timeout_report_payload が正しい辞書を返すことをテストする。
    """
    payload = create_timeout_report_payload()
    assert payload == {
        "error": TIMEOUT_ERROR_MESSAGE,
        "changed_files": []
    }

    custom_message = "CUSTOM_TIMEOUT_ERROR"
    payload_custom = create_timeout_report_payload(custom_message)
    assert payload_custom == {
        "error": custom_message,
        "changed_files": []
    }

    payload_with_files = create_timeout_report_payload(custom_message, ["file1.py", "file2.py"])
    assert payload_with_files == {
        "error": custom_message,
        "changed_files": ["file1.py", "file2.py"]
    }


def test_parse_arguments():
    """
    parse_arguments が引数を正しくパースし、デフォルト値が適切に設定されることをテストする。
    """
    # 引数なし（デフォルト値）
    args = parse_arguments()
    assert args.task_id == DEFAULT_TIMEOUT_TASK_ID
    assert args.error == TIMEOUT_ERROR_MESSAGE
    assert args.changed_files is None


    # 引数あり
    args_custom = parse_arguments(["--task-id", "custom-task-123", "--error", "custom-error-msg", "--changed-files", "file1.py", "file2.py"])
    assert args_custom.task_id == "custom-task-123"
    assert args_custom.error == "custom-error-msg"
    assert args_custom.changed_files == ["file1.py", "file2.py"]


@patch("backend.agents.orchestration.mark_fail_batch_6d239c_agent4.OrchestrationHub")
def test_mark_timeout_failure(mock_hub_class):
    """
    mark_timeout_failure が正しい引数で mark_task_done を呼び出すことをテストする。
    """
    mock_hub_instance = MagicMock()
    mock_hub_class.return_value = mock_hub_instance

    # デフォルト値での呼び出し
    mark_timeout_failure("test-task-123")
    mock_hub_instance.mark_task_done.assert_called_with(
        "test-task-123",
        "fail",
        {
            "error": TIMEOUT_ERROR_MESSAGE,
            "changed_files": []
        }
    )

    # カスタム引数での呼び出し
    mock_hub_instance.reset_mock()
    mark_timeout_failure(
        task_id="test-task-456",
        error_message="custom error",
        changed_files=["a.py", "b.py"]
    )
    mock_hub_instance.mark_task_done.assert_called_once_with(
        "test-task-456",
        "fail",
        {
            "error": "custom error",
            "changed_files": ["a.py", "b.py"]
        }
    )


@patch("backend.agents.orchestration.mark_fail_batch_6d239c_agent4.mark_timeout_failure")
def test_main(mock_mark_task):
    """
    main 関数が引数なしで実行された際に、デフォルトの引数で mark_timeout_failure を呼び出すことをテストする。
    """
    main()
    mock_mark_task.assert_called_once_with(
        task_id=DEFAULT_TIMEOUT_TASK_ID,
        error_message=TIMEOUT_ERROR_MESSAGE,
        changed_files=None
    )


@patch("backend.agents.orchestration.mark_fail_batch_6d239c_agent4.mark_timeout_failure")
def test_main_with_arguments(mock_mark_task):
    """
    main 関数がコマンドライン引数ありで実行された際に、指定の引数で mark_timeout_failure を呼び出すことをテストする。
    """
    main(["--task-id", "custom-task-123", "--error", "custom-error-msg", "--changed-files", "file1.py", "file2.py"])
    mock_mark_task.assert_called_once_with(
        task_id="custom-task-123",
        error_message="custom-error-msg",
        changed_files=["file1.py", "file2.py"]
    )


@patch("backend.agents.orchestration.OrchestrationHub")
def test_script_as_main(mock_hub_class):
    """
    スクリプトが __main__ として実行されたときの動作をテストする。
    """
    mock_hub_instance = MagicMock()
    mock_hub_class.return_value = mock_hub_instance

    # sys.path から一時的にルートパスを除外して、not in sys.path 条件を通す
    root_path_str = str(Path(__file__).resolve().parents[2])
    path_removed = False
    if root_path_str in sys.path:
        sys.path.remove(root_path_str)
        path_removed = True

    try:
        # runpy を使って __main__ として実行する
        # このとき pytest の sys.argv がパースされないよう、sys.argv をモックする
        script_path = str(Path(__file__).resolve().parents[1] / "agents" / "orchestration" / "mark_fail_batch_6d239c_agent4.py")
        with patch("sys.argv", ["mark_fail_batch_6d239c_agent4.py"]):
            runpy.run_path(script_path, run_name="__main__")
    finally:
        if path_removed and root_path_str not in sys.path:
            sys.path.insert(0, root_path_str)

    # OrchestrationHub.mark_task_done がデフォルトタスクで呼ばれることを確認
    mock_hub_instance.mark_task_done.assert_called_once_with(
        DEFAULT_TIMEOUT_TASK_ID,
        "fail",
        {
            "error": TIMEOUT_ERROR_MESSAGE,
            "changed_files": []
        }
    )


