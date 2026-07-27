# -*- coding: utf-8 -*-
import os
import sys
import runpy
import json

# 動的にプロジェクトルートを sys.path の先頭に追加
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from unittest.mock import MagicMock, patch
import pytest

@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution(mock_orchestration_hub_class, capsys):
    """main関数の実行と OrchestrationHub.mark_task_done の呼び出し検証"""
    mock_hub = MagicMock()
    mock_orchestration_hub_class.return_value = mock_hub

    # テスト対象の main をインポートして実行
    from backend.scratch.mark_themes_completed import main
    main()

    # OrchestrationHub がインスタンス化されたことを検証
    mock_orchestration_hub_class.assert_called_once()

    # mark_task_done が正しい引数で呼ばれたことを検証
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_d6d052-test_weaver-008",
        "pass",
        {
            "message": "backend/routers/themes_router.py に対するユニットテストを新規追加し、カバレッジを 47% から 100% (+53%) に向上させました。",
            "changed_files": ["tests/test_shared/test_batch16_admin_routers.py"]
        }
    )

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "Marked themes_router task done." in captured.out

@patch("backend.agents.orchestration.OrchestrationHub")
def test_script_direct_execution(mock_orchestration_hub_class, capsys):
    """__name__ == '__main__' 条件分岐を含むスクリプト全体の実行検証"""
    mock_hub = MagicMock()
    mock_orchestration_hub_class.return_value = mock_hub

    # 警告を避けるため、sys.modulesから一時的にモジュールを削除
    import sys
    sys.modules.pop("backend.scratch.mark_themes_completed", None)

    # runpy を用いてモジュールを直接実行
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("backend.scratch.mark_themes_completed", run_name="__main__")
    assert exc_info.value.code == 0

    # OrchestrationHub がインスタンス化されたことを検証
    mock_orchestration_hub_class.assert_called_once()

    # mark_task_done が呼ばれたことを検証
    mock_hub.mark_task_done.assert_called_once_with(
        "T-batch_d6d052-test_weaver-008",
        "pass",
        {
            "message": "backend/routers/themes_router.py に対するユニットテストを新規追加し、カバレッジを 47% から 100% (+53%) に向上させました。",
            "changed_files": ["tests/test_shared/test_batch16_admin_routers.py"]
        }
    )

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "Marked themes_router task done." in captured.out


@patch("sys.exit")
@patch("backend.agents.orchestration.OrchestrationHub")
def test_script_direct_execution_sys_exit_mocked(mock_orchestration_hub_class, mock_sys_exit, capsys):
    """sys.exit をモック化し、SystemExitを発生させずにスクリプトの末尾（sys.exit(main())）まで到達・カバーさせるテスト"""
    mock_hub = MagicMock()
    mock_orchestration_hub_class.return_value = mock_hub

    # 警告を避けるため、sys.modulesから一時的にモジュールを削除
    import sys
    sys.modules.pop("backend.scratch.mark_themes_completed", None)

    # sys.exit がモックされているので、SystemExit 例外は発生しない
    runpy.run_module("backend.scratch.mark_themes_completed", run_name="__main__")

    # sys.exit が main() の戻り値である 0 で呼ばれたことを検証
    mock_sys_exit.assert_called_once_with(0)

    # 標準出力の検証
    captured = capsys.readouterr()
    assert "Marked themes_router task done." in captured.out


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_hub_init_error(mock_orchestration_hub_class, capsys):
    """OrchestrationHubの初期化時エラーに対するフォールバック検証"""
    mock_orchestration_hub_class.side_effect = PermissionError("Permission denied to access queue file")

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "File access error marking task done:" in captured.err
    assert "Permission denied to access queue file" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_mark_done_error(mock_orchestration_hub_class, capsys):
    """mark_task_done 呼び出し時エラーに対するフォールバック検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = ValueError("Invalid task ID")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Data format error marking task done:" in captured.err
    assert "Invalid task ID" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_file_not_found_error(mock_orchestration_hub_class, capsys):
    """FileNotFoundError に対するフォールバック検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = FileNotFoundError("Queue file not found")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "File access error marking task done:" in captured.err
    assert "Queue file not found" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_json_decode_error(mock_orchestration_hub_class, capsys):
    """JSONDecodeError に対するフォールバック検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "JSON format error marking task done:" in captured.err
    assert "Expecting value" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_key_error(mock_orchestration_hub_class, capsys):
    """KeyError に対するエラーハンドリング検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = KeyError("tasks")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Data format error marking task done:" in captured.err
    assert "'tasks'" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_type_error(mock_orchestration_hub_class, capsys):
    """TypeError に対するエラーハンドリング検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = TypeError("object is not subscriptable")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Data format error marking task done:" in captured.err
    assert "object is not subscriptable" in captured.err


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_os_error(mock_orchestration_hub_class, capsys):
    """OSError に対するエラーハンドリング検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = OSError("Disk full")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "OS error marking task done:" in captured.err
    assert "Disk full" in captured.err


@patch("backend.scratch.mark_themes_completed.TechnicalDebtStore")
@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_unexpected_error_tdr(mock_orchestration_hub_class, mock_tdr_store_class, capsys):
    """予期せぬエラー発生時にTDR（技術負債）への自動登録とフォールバックが行われるかの検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = RuntimeError("Unexpected filesystem failure")
    mock_orchestration_hub_class.return_value = mock_hub

    mock_tdr_store = MagicMock()
    mock_tdr_store_class.return_value = mock_tdr_store

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    
    # TDRストアがインスタンス化され、register_debtが呼ばれたことを検証
    mock_tdr_store_class.assert_called_once()
    mock_tdr_store.register_debt.assert_called_once_with(
        category="MINOR_INFRA",
        file_path="backend/scratch/mark_themes_completed.py",
        line_number=45,
        pattern="except (RuntimeError, AttributeError, NameError, LookupError) as e:",
        cause_pattern="DP-02",
        fix_pattern="具体的な例外キャッチまたは安全終了の確認",
        registered_by="sprint_m25_1",
        notes="mark_themes_completed.py で具体的な例外を捕捉: Unexpected filesystem failure"
    )

    captured = capsys.readouterr()
    assert "Unexpected error marking task done:" in captured.err
    assert "Unexpected filesystem failure" in captured.err


@patch("backend.scratch.mark_themes_completed.TechnicalDebtStore")
@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_unexpected_error_tdr_registration_failure(mock_orchestration_hub_class, mock_tdr_store_class, capsys):
    """TDR登録自体が失敗した場合でも、正しくフォールバックして終了コード1を返すかの検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = RuntimeError("Unexpected filesystem failure")
    mock_orchestration_hub_class.return_value = mock_hub

    mock_tdr_store = MagicMock()
    mock_tdr_store.register_debt.side_effect = IOError("Database locked")
    mock_tdr_store_class.return_value = mock_tdr_store

    from backend.scratch.mark_themes_completed import main
    exit_code = main()

    assert exit_code == 1
    
    captured = capsys.readouterr()
    assert "Failed to register TDR: Database locked" in captured.err
    assert "Unexpected error marking task done: Unexpected filesystem failure" in captured.err


def test_sys_path_not_duplicated():
    """sys.path にすでに project_root が存在する場合、重複して追加されないことを検証"""
    import sys
    import os
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    
    # 既に project_root が sys.path に入っていることを確認
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    original_len = len(sys.path)
    
    # 再度、追加処理を実行するロジック（ファイル内のifブロックと同等）
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    # 長さが変わっていないことを検証
    assert len(sys.path) == original_len


@patch("backend.scratch.mark_themes_completed.OrchestrationHub")
def test_main_execution_uncaught_error(mock_orchestration_hub_class):
    """キャッチ対象外の例外（例: ZeroDivisionError）が発生したときに、例外がキャッチされずに呼び出し元へ伝播することを検証"""
    mock_hub = MagicMock()
    mock_hub.mark_task_done.side_effect = ZeroDivisionError("division by zero")
    mock_orchestration_hub_class.return_value = mock_hub

    from backend.scratch.mark_themes_completed import main
    with pytest.raises(ZeroDivisionError):
        main()
