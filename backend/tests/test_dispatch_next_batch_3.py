import os
import sys
import pytest
import json
import importlib
import runpy
from unittest.mock import MagicMock, patch

# プロジェクトのルートパスを sys.path に追加して、backend/scratch/dispatch_next_batch_3.py がインポートできるようにする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.scratch.dispatch_next_batch_3 import run_dispatch, main, register_technical_debt

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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27", "--milestone", "M27.1", "--batch-size", "10"])
        assert batch == {"batch_id": "batch_456"}
        mock_hub_instance.get_phase_state.assert_not_called()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=10)

def test_run_dispatch_state_not_dict():
    # get_phase_state の戻り値が辞書ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None  # 辞書ではない

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_milestone must be str"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_state_exception():
    # get_phase_state で予期せぬ例外が発生する場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("DB connection lost")

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="DB connection lost"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_invalid_batch_size():
    # batch_size が非正または不正な型の場合
    mock_hub_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch([])
        assert batch is None


def test_register_technical_debt_internal_exception(capsys):
    # register_technical_debt 内部で例外が発生した際のハンドリング
    with patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", side_effect=Exception("Disk full")):
        register_technical_debt(70, "test pattern", "test notes")
        
        # sys.stderr の出力を検証
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Disk full" in captured.err

def test_main_success(capsys):
    # main() の正常終了ケース
    mock_batch = {"batch_id": "batch_abc", "tasks": []}
    with patch("backend.scratch.dispatch_next_batch_3.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 0
        
        captured = capsys.readouterr()
        assert "BATCH_START" in captured.out
        assert "batch_abc" in captured.out
        assert "BATCH_END" in captured.out

def test_main_returns_none(capsys):
    # run_dispatch が None を返すケース
    with patch("backend.scratch.dispatch_next_batch_3.run_dispatch", return_value=None):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "No batch returned." in captured.err

def test_main_serialization_error(capsys):
    # json シリアライズエラーが発生するケース（辞書の中にセットを入れる）
    mock_batch = {"invalid": {1, 2, 3}}
    with patch("backend.scratch.dispatch_next_batch_3.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "JSON serialization error" in captured.err

def test_main_exception(capsys):
    # run_dispatch が例外を投げるケース
    with patch("backend.scratch.dispatch_next_batch_3.run_dispatch", side_effect=ValueError("Invalid phase")):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Dispatch failed: Invalid phase" in captured.err

def test_path_insertion():
    # sys.path にルートパスが含まれていない状態を再現してリロードする
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == "tests":
        parent_dir = os.path.dirname(script_dir)
        if os.path.basename(parent_dir) == "backend":
            project_root = os.path.dirname(parent_dir)
        else:
            project_root = parent_dir
    else:
        project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    project_root_norm = os.path.normcase(os.path.abspath(project_root))
    
    # sys.path から project_root を一時的に除去
    original_path = sys.path.copy()
    sys.path = [p for p in sys.path if os.path.normcase(os.path.abspath(p)) != project_root_norm]
    
    try:
        # キャッシュからモジュールを削除して、再度インポートした際にインポート時コードが実行されるようにする
        if "backend.scratch.dispatch_next_batch_3" in sys.modules:
            del sys.modules["backend.scratch.dispatch_next_batch_3"]
            
        import backend.scratch.dispatch_next_batch_3
    finally:
        sys.path = original_path

def test_main_as_script():
    # __name__ == "__main__" のブロックを実行する
    mock_batch = {"batch_id": "batch_runpy"}
    
    # dispatch_next_batch_3.py の絶対パスを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == "tests":
        parent_dir = os.path.dirname(script_dir)
        if os.path.basename(parent_dir) == "backend":
            project_root = os.path.dirname(parent_dir)
        else:
            project_root = parent_dir
    else:
        project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    target_script = os.path.abspath(os.path.join(project_root, "backend", "scratch", "dispatch_next_batch_3.py"))
    
    with patch("backend.scratch.dispatch_next_batch_3.run_dispatch", return_value=mock_batch), \
         patch("sys.argv", [target_script]):
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(target_script, run_name="__main__")
        assert exit_info.value.code == 0

def test_register_technical_debt_success():
    # register_technical_debt の正常系テスト
    from backend.scratch.dispatch_next_batch_3 import register_technical_debt
    mock_store_instance = MagicMock()
    with patch("backend.scratch.dispatch_next_batch_3.TechnicalDebtStore", return_value=mock_store_instance):
        register_technical_debt(42, "test_pattern", "test_notes")
        mock_store_instance.register_debt.assert_called_once_with(
            category="MINOR_INFRA",
            file_path="backend/scratch/dispatch_next_batch_3.py",
            line_number=42,
            pattern="test_pattern",
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes="test_notes",
            tags=["dispatch_next_batch_3", "except_exception"]
        )

def test_run_dispatch_argument_parse_error():
    # 不正なオプションや引数の型エラーで argparse.ArgumentParser が SystemExit を投げること
    from backend.scratch.dispatch_next_batch_3 import run_dispatch
    with pytest.raises(SystemExit):
        run_dispatch(["--unknown-argument"])

    with pytest.raises(SystemExit):
        run_dispatch(["--phase", "invalid_int_value"])

def test_run_dispatch_args_none():
    # args=None の場合に sys.argv から正しく解析されること
    from backend.scratch.dispatch_next_batch_3 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {"batch_id": "batch_sys_argv"}
    
    test_args = ["dispatch_next_batch_3.py", "--phase", "12", "--milestone", "M12", "--batch-size", "5"]
    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance), \
         patch("sys.argv", test_args):
        batch = run_dispatch(None)
        assert batch == {"batch_id": "batch_sys_argv"}
        mock_hub_instance.get_next_batch.assert_called_once_with(12, "M12", batch_size=5)


def test_run_dispatch_milestone_only_none():
    # phase は指定、milestone は None のため get_phase_state から milestone のみ取得されるケース
    from backend.scratch.dispatch_next_batch_3 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_milestone_only_none"
    }

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27"])
        assert batch == {"batch_id": "batch_milestone_only_none"}
        mock_hub_instance.get_phase_state.assert_called_once()
        # phase は引数指定の 27, milestone は state から取得された "M26.1" になること
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M26.1", batch_size=6)

def test_run_dispatch_phase_only_none():
    # milestone は指定、phase は None のため get_phase_state から phase のみ取得されるケース
    from backend.scratch.dispatch_next_batch_3 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_phase_only_none"
    }

    with patch("backend.scratch.dispatch_next_batch_3.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--milestone", "M27.1"])
        assert batch == {"batch_id": "batch_phase_only_none"}
        mock_hub_instance.get_phase_state.assert_called_once()
        # phase は state から取得された 26, milestone は引数指定の "M27.1" になること
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M27.1", batch_size=6)
