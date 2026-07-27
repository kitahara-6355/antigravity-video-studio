import os
import sys
import pytest
import json
import importlib
import runpy
from unittest.mock import MagicMock, patch

# プロジェクトのルートパスを sys.path に追加して、backend/scratch/dispatch_tasks.py がインポートできるようにする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.scratch.dispatch_tasks import run_dispatch, main, register_technical_debt

def test_run_dispatch_success_no_args():
    # 引数なしの正常系
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_123",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch([])
        assert batch == {
            "batch_id": "batch_123",
            "tasks": [{"task_id": "T-1", "status": "pending"}]
        }
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M26.1", batch_size=6)

def test_run_dispatch_success_with_args():
    # 引数指定の正常系
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_456"
    }

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27", "--milestone", "M27.1", "--batch-size", "10"])
        assert batch == {"batch_id": "batch_456"}
        mock_hub_instance.get_phase_state.assert_not_called()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=10)

def test_run_dispatch_state_not_dict():
    # get_phase_state の戻り値が辞書ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None  # 辞書ではない

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="get_phase_state returned non-dict type"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_phase_missing():
    # get_phase_state で current_phase が欠損している場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_milestone": "M26.1"
    }

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(KeyError, match="get_phase_state missing 'current_phase'"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_phase_not_int():
    # current_phase が整数ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": "twenty-six",
        "current_milestone": "M26.1"
    }

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_phase must be int"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_milestone_missing():
    # current_milestone が欠損している場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26
    }

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(KeyError, match="get_phase_state missing 'current_milestone'"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_milestone_not_str():
    # current_milestone が文字列ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": 123
    }

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_milestone must be str"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_state_exception():
    # get_phase_state で予期せぬ例外が発生する場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("DB connection lost")

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="DB connection lost"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_invalid_batch_size():
    # batch_size が非正または不正な型の場合
    mock_hub_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch(["--phase", "26", "--milestone", "M26.1", "--batch-size", "0"])

        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch(["--phase", "26", "--milestone", "M26.1", "--batch-size", "-5"])

def test_run_dispatch_next_batch_exception():
    # get_next_batch で予期せぬ例外が発生する場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.side_effect = RuntimeError("Failed to fetch batch")

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Failed to fetch batch"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_next_batch_returns_none():
    # get_next_batch が None を返す場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = None

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch([])
        assert batch is None

def test_register_technical_debt_internal_exception(capsys):
    # register_technical_debt 内部で例外が発生した際のハンドリング
    with patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", side_effect=OSError("Disk full")):
        register_technical_debt(70, "test pattern", "test notes")
        
        # sys.stderr の出力を検証
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Disk full" in captured.err

def test_main_success(capsys):
    # main() の正常終了ケース
    mock_batch = {"batch_id": "batch_abc", "tasks": []}
    with patch("backend.scratch.dispatch_tasks.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 0
        
        captured = capsys.readouterr()
        assert "batch_abc" in captured.out

def test_main_returns_none(capsys):
    # run_dispatch が None を返すケース
    with patch("backend.scratch.dispatch_tasks.run_dispatch", return_value=None):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "No batch returned." in captured.err

def test_main_serialization_error(capsys):
    # json シリアライズエラーが発生するケース（辞書の中にセットを入れる）
    mock_batch = {"invalid": {1, 2, 3}}
    with patch("backend.scratch.dispatch_tasks.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "JSON serialization error" in captured.err

def test_main_exception(capsys):
    # run_dispatch が例外を投げるケース
    with patch("backend.scratch.dispatch_tasks.run_dispatch", side_effect=ValueError("Invalid phase")):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Dispatch failed: Invalid phase" in captured.err

def test_path_insertion():
    # sys.path にルートパスが含まれていない状態を再現してリロードする
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    
    # sys.path から project_root を一時的に除去
    original_path = sys.path.copy()
    sys.path = [p for p in sys.path if os.path.abspath(p) != project_root]
    
    try:
        import backend.scratch.dispatch_tasks
        importlib.reload(backend.scratch.dispatch_tasks)
    finally:
        sys.path = original_path

def test_main_as_script():
    # __name__ == "__main__" のブロックを実行する
    mock_batch = {"batch_id": "batch_runpy"}
    
    # dispatch_tasks.py の絶対パスを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_script = os.path.abspath(os.path.join(script_dir, "..", "backend", "scratch", "dispatch_tasks.py"))
    
    with patch("backend.scratch.dispatch_tasks.run_dispatch", return_value=mock_batch), \
         patch("sys.argv", [target_script]):
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(target_script, run_name="__main__")
        assert exit_info.value.code == 0


def test_run_dispatch_only_phase_provided():
    # phase のみ指定され、milestone は get_phase_state から取得するケース (64->80 ブランチの網羅)
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_only_phase"
    }

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27"])
        assert batch == {"batch_id": "batch_only_phase"}
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M26.1", batch_size=6)

def test_run_dispatch_only_milestone_provided():
    # milestone のみ指定され、phase は get_phase_state から取得するケース (57->64 ブランチの網羅)
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_only_milestone"
    }

    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--milestone", "M27.1"])
        assert batch == {"batch_id": "batch_only_milestone"}
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M27.1", batch_size=6)


def test_run_dispatch_argparse_error():
    # 無効な引数を渡したときに argparse が SystemExit を送出することを確認
    with pytest.raises(SystemExit):
        run_dispatch(["--invalid-argument"])


def test_register_technical_debt_success():
    # register_technical_debt の正常系動作確認
    mock_store_instance = MagicMock()
    with patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", return_value=mock_store_instance):
        register_technical_debt(100, "dummy_pattern", "dummy_notes")
        mock_store_instance.register_debt.assert_called_once_with(
            category="MINOR_INFRA",
            file_path="backend/scratch/dispatch_tasks.py",
            line_number=100,
            pattern="dummy_pattern",
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes="dummy_notes",
            tags=["dispatch_tasks", "except_exception"]
        )


def test_main_argparse_error_handling():
    # main() 実行時に sys.argv に無効な引数が入っていた場合の SystemExit
    with patch("sys.argv", ["dispatch_tasks.py", "--invalid-argument-for-main"]):
        with pytest.raises(SystemExit):
            main()


def test_run_dispatch_invalid_phase_type():
    # --phase に整数に変換できない文字列が渡された場合、argparse が SystemExit を送出することを確認
    with pytest.raises(SystemExit):
        run_dispatch(["--phase", "abc"])


def test_run_dispatch_default_args():
    # args=None の場合、sys.argv から引数を取得してパースすることを確認
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_sys_argv"
    }

    # sys.argv をモック化し、引数なし（スクリプト名のみ）で呼び出された場合をシミュレート
    with patch("backend.scratch.dispatch_tasks.OrchestrationHub", return_value=mock_hub_instance), \
         patch("sys.argv", ["dispatch_tasks.py"]):
        batch = run_dispatch(None)
        assert batch == {"batch_id": "batch_sys_argv"}
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M26.1", batch_size=6)


def test_main_unexpected_serialization_exception(capsys):
    # json.dumps 内で TypeError, ValueError 以外の例外（例: RuntimeError）が発生した場合の main() のハンドリング
    mock_batch = {"some": "data"}
    with patch("backend.scratch.dispatch_tasks.run_dispatch", return_value=mock_batch), \
         patch("json.dumps", side_effect=RuntimeError("Unexpected serialization error")):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Dispatch failed: Unexpected serialization error" in captured.err

def test_register_technical_debt_other_specific_exceptions(capsys):
    # TypeError や ValueError が発生した場合でも適切にキャッチしてログ出力すること
    with patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", side_effect=TypeError("Invalid type")):
        register_technical_debt(70, "test pattern", "test notes")
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Invalid type" in captured.err

    with patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", side_effect=ValueError("Invalid value")):
        register_technical_debt(70, "test pattern", "test notes")
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Invalid value" in captured.err

def test_register_technical_debt_uncaught_exception():
    # 捕捉対象外の例外（例: RuntimeError）が register_technical_debt 内で発生した場合は上に伝播すること
    with patch("backend.scratch.dispatch_tasks.TechnicalDebtStore", side_effect=RuntimeError("Uncaught system error")):
        with pytest.raises(RuntimeError, match="Uncaught system error"):
            register_technical_debt(70, "test pattern", "test notes")
