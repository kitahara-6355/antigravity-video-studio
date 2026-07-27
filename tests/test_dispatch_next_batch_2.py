import os
import sys
import pytest
import json
import importlib
import runpy
from unittest.mock import MagicMock, patch

# プロジェクトのルートパスを sys.path に追加して、backend/scratch/dispatch_next_batch_2.py がインポートできるようにする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.scratch.dispatch_next_batch_2 import run_dispatch, main, register_technical_debt

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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27", "--milestone", "M27.1", "--batch-size", "10"])
        assert batch == {"batch_id": "batch_456"}
        mock_hub_instance.get_phase_state.assert_not_called()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=10)

def test_run_dispatch_state_not_dict():
    # get_phase_state の戻り値が辞書ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None  # 辞書ではない

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_milestone must be str"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_state_exception():
    # get_phase_state で予期せぬ例外が発生する場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("DB connection lost")

    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="DB connection lost"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_invalid_batch_size():
    # batch_size が非正または不正な型の場合
    mock_hub_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
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

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch([])
        assert batch is None


def test_register_technical_debt_internal_exception(capsys):
    # register_technical_debt 内部で例外が発生した際のハンドリング
    with patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", side_effect=Exception("Disk full")):
        register_technical_debt(70, "test pattern", "test notes")
        
        # sys.stderr の出力を検証
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Disk full" in captured.err

def test_main_success(capsys):
    # main() の正常終了ケース
    mock_batch = {"batch_id": "batch_abc", "tasks": []}
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 0
        
        captured = capsys.readouterr()
        assert "BATCH_START" in captured.out
        assert "batch_abc" in captured.out
        assert "BATCH_END" in captured.out

def test_main_returns_none(capsys):
    # run_dispatch が None を返すケース
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", return_value=None):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "No batch returned." in captured.err

def test_main_serialization_error(capsys):
    # json シリアライズエラーが発生するケース（辞書の中にセットを入れる）
    mock_batch = {"invalid": {1, 2, 3}}
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", return_value=mock_batch):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "JSON serialization error" in captured.err

def test_main_exception(capsys):
    # run_dispatch が例外を投げるケース
    mock_store_instance = MagicMock()
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", side_effect=ValueError("Invalid phase")), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "Dispatch failed: Invalid phase" in captured.err
        
        # TDR登録が呼ばれることの検証
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        assert called_kwargs["line_number"] == 146
        assert "Dispatch failed: Invalid phase" in called_kwargs["notes"]

def test_path_insertion():
    # sys.path にルートパスおよび backend パスが含まれていない状態を再現してリロードする
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
    backend_dir_norm = os.path.normcase(os.path.abspath(os.path.join(project_root, "backend")))
    
    # sys.path から project_root と backend_dir を一時的に除去
    original_path = sys.path.copy()
    sys.path = [
        p for p in sys.path 
        if os.path.normcase(os.path.abspath(p)) != project_root_norm 
        and os.path.normcase(os.path.abspath(p)) != backend_dir_norm
    ]
    
    try:
        # キャッシュからモジュールを削除して、再度インポートした際にインポート時コードが実行されるようにする
        if "backend.scratch.dispatch_next_batch_2" in sys.modules:
            del sys.modules["backend.scratch.dispatch_next_batch_2"]
            
        import backend.scratch.dispatch_next_batch_2
    finally:
        sys.path = original_path


def test_main_as_script():
    # __name__ == "__main__" のブロックを実行する
    mock_batch = {"batch_id": "batch_runpy"}
    
    # dispatch_next_batch_2.py の絶対パスを取得
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == "tests":
        parent_dir = os.path.dirname(script_dir)
        if os.path.basename(parent_dir) == "backend":
            project_root = os.path.dirname(parent_dir)
        else:
            project_root = parent_dir
    else:
        project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    target_script = os.path.abspath(os.path.join(project_root, "backend", "scratch", "dispatch_next_batch_2.py"))
    
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", return_value=mock_batch), \
         patch("sys.argv", [target_script]):
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(target_script, run_name="__main__")
        assert exit_info.value.code == 0

def test_register_technical_debt_success():
    # register_technical_debt の正常系テスト
    from backend.scratch.dispatch_next_batch_2 import register_technical_debt
    mock_store_instance = MagicMock()
    with patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        register_technical_debt(42, "test_pattern", "test_notes")
        mock_store_instance.register_debt.assert_called_once_with(
            category="MINOR_INFRA",
            file_path="scratch/dispatch_next_batch_2.py",
            line_number=42,
            pattern="test_pattern",
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes="test_notes",
            tags=["dispatch_next_batch_2", "except_exception"]
        )

def test_run_dispatch_argument_parse_error():
    # 不正なオプションや引数の型エラーで argparse.ArgumentParser が SystemExit を投げること
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    with pytest.raises(SystemExit):
        run_dispatch(["--unknown-argument"])

    with pytest.raises(SystemExit):
        run_dispatch(["--phase", "invalid_int_value"])

def test_run_dispatch_args_none():
    # args=None の場合に sys.argv から正しく解析されること
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {"batch_id": "batch_sys_argv"}
    
    test_args = ["dispatch_next_batch_2.py", "--phase", "12", "--milestone", "M12", "--batch-size", "5"]
    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("sys.argv", test_args):
        batch = run_dispatch(None)
        assert batch == {"batch_id": "batch_sys_argv"}
        mock_hub_instance.get_next_batch.assert_called_once_with(12, "M12", batch_size=5)


def test_run_dispatch_milestone_only_none():
    # phase は指定、milestone は None のため get_phase_state から milestone のみ取得されるケース
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_milestone_only_none"
    }

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--phase", "27"])
        assert batch == {"batch_id": "batch_milestone_only_none"}
        mock_hub_instance.get_phase_state.assert_called_once()
        # phase は引数指定の 27, milestone は state から取得された "M26.1" になること
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M26.1", batch_size=6)

def test_run_dispatch_phase_only_none():
    # milestone は指定、phase は None のため get_phase_state から phase のみ取得されるケース
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_phase_only_none"
    }

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        batch = run_dispatch(["--milestone", "M27.1"])
        assert batch == {"batch_id": "batch_phase_only_none"}
        mock_hub_instance.get_phase_state.assert_called_once()
        # phase は state から取得された 26, milestone は引数指定の "M27.1" になること
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M27.1", batch_size=6)

def test_register_technical_debt_exact_line_number_from_exception():
    # run_dispatch を実行して意図的に例外を発生させ、
    # register_technical_debt が正しい line_number (118) で呼び出されるか検証する
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.side_effect = RuntimeError("Mocked Hub Failure")
    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Mocked Hub Failure"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        line_number = called_kwargs["line_number"]
        # dispatch_next_batch_2.py 内で get_next_batch は 113行目付近
        # 登録される line_number は 118 (except 句の開始行)
        assert line_number == 118

def test_run_dispatch_heartbeat_only_success():
    # --heartbeat-only オプションの正常系テスト
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch(["--heartbeat-only"])
        assert result == {"heartbeat_only": True}
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.get_next_batch.assert_not_called()

def test_run_dispatch_heartbeat_only_exception():
    # --heartbeat-only オプションで例外が発生する異常系テスト
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Heartbeat failed")
    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Heartbeat failed"):
            run_dispatch(["--heartbeat-only"])
        
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        assert called_kwargs["line_number"] == 53
        assert "Failed to update heartbeat: Heartbeat failed" in called_kwargs["notes"]

def test_run_dispatch_update_heartbeat_success():
    # --update-heartbeat オプションの正常系テスト
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {"batch_id": "batch_update_heartbeat"}

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch(["--phase", "27", "--milestone", "M27.1", "--update-heartbeat"])
        assert result == {"batch_id": "batch_update_heartbeat"}
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)

def test_run_dispatch_update_heartbeat_exception():
    # --update-heartbeat オプションで心拍更新に失敗する異常系テスト
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Heartbeat failed pre-dispatch")
    mock_store_instance = MagicMock()

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Heartbeat failed pre-dispatch"):
            run_dispatch(["--phase", "27", "--milestone", "M27.1", "--update-heartbeat"])
        
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        assert called_kwargs["line_number"] == 66
        assert "Failed to update heartbeat (pre-dispatch): Heartbeat failed pre-dispatch" in called_kwargs["notes"]

def test_main_heartbeat_only_exit(capsys):
    # run_dispatch が {"heartbeat_only": True} を返す場合の main() の正常終了
    from backend.scratch.dispatch_next_batch_2 import main
    mock_res = {"heartbeat_only": True}
    with patch("backend.scratch.dispatch_next_batch_2.run_dispatch", return_value=mock_res):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 0
        
        captured = capsys.readouterr()
        assert "HEARTBEAT_UPDATED" in captured.out


def test_run_dispatch_invalid_batch_size_type():
    # batch_size が float や list などの非 int 型の場合の ValueError ハンドリング
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }

    # argparse をモックして batch_size が float や list になるように Namespace を偽装する
    mock_args = MagicMock()
    mock_args.phase = 26
    mock_args.milestone = "M26.1"
    mock_args.batch_size = 6.5  # float
    mock_args.heartbeat_only = False
    mock_args.update_heartbeat = False

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("argparse.ArgumentParser.parse_args", return_value=mock_args):
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch([])

    # list の場合
    mock_args.batch_size = [6]
    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("argparse.ArgumentParser.parse_args", return_value=mock_args):
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch([])

def test_run_dispatch_state_invalid_types():
    # get_phase_state() の戻り値として、不正なデータ型（list や dict）が含まれている場合
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_store_instance = MagicMock()

    # current_phase が list の場合
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": [26],
        "current_milestone": "M26.1"
    }
    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_phase must be int"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_called_once()

    mock_store_instance.reset_mock()

    # current_milestone が dict の場合
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": {"name": "M26.1"}
    }
    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_milestone must be str"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_called_once()

def test_register_technical_debt_with_unicode():
    # register_technical_debt に日本語などのマルチバイト文字が含まれている場合の正常登録動作確認
    from backend.scratch.dispatch_next_batch_2 import register_technical_debt
    mock_store_instance = MagicMock()
    with patch("backend.scratch.dispatch_next_batch_2.TechnicalDebtStore", return_value=mock_store_instance):
        register_technical_debt(99, "パターンテスト日本語", "ノートテスト日本語")
        mock_store_instance.register_debt.assert_called_once_with(
            category="MINOR_INFRA",
            file_path="scratch/dispatch_next_batch_2.py",
            line_number=99,
            pattern="パターンテスト日本語",
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_thumbnail",
            notes="ノートテスト日本語",
            tags=["dispatch_next_batch_2", "except_exception"]
        )

def test_run_dispatch_default_arguments():
    # 引数を明示的に指定しない場合のデフォルト値パース動作確認
    from backend.scratch.dispatch_next_batch_2 import run_dispatch
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {"batch_id": "batch_default"}

    with patch("backend.scratch.dispatch_next_batch_2.OrchestrationHub", return_value=mock_hub_instance), \
         patch("sys.argv", ["dispatch_next_batch_2.py"]):
        batch = run_dispatch(None)
        assert batch == {"batch_id": "batch_default"}
        mock_hub_instance.get_next_batch.assert_called_once_with(26, "M26.1", batch_size=6)
