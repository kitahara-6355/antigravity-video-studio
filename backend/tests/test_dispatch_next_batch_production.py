import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch

# プロジェクトのルートパスを sys.path に追加して、インポートを可能にする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# プロダクションコードからインポート
from backend.agents.orchestration.dispatch_next_batch import run_dispatch, main, register_technical_debt

def test_run_dispatch_success_no_args():
    # 引数なしの正常系
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_123",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }
    mock_hub_instance.get_queue_status.return_value = {"total_tasks": 1}
    mock_hub_instance.generate_flash_status.return_value = {"success_rate": 100}

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch([])
        assert result["phase"] == 27
        assert result["milestone"] == "M27.1"
        assert result["batch"] == {
            "batch_id": "batch_123",
            "tasks": [{"task_id": "T-1", "status": "pending"}]
        }
        assert result["queue_status"] == {"total_tasks": 1}
        assert result["status"] == {"success_rate": 100}
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("ce05d36d-f2c8-452b-8ea9-9053a1e718a0")
        mock_hub_instance.get_phase_state.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)

def test_run_dispatch_success_with_args():
    # 引数指定の正常系
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_456"
    }
    mock_hub_instance.get_queue_status.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = {}

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch([
            "--phase", "28",
            "--milestone", "M28.1",
            "--batch-size", "10",
            "--conversation-id", "custom_id"
        ])
        assert result["batch"] == {"batch_id": "batch_456"}
        mock_hub_instance.register_flash_conversation_id.assert_called_once_with("custom_id")
        mock_hub_instance.get_phase_state.assert_not_called()
        mock_hub_instance.get_next_batch.assert_called_once_with(28, "M28.1", batch_size=10)

def test_run_dispatch_heartbeat_only():
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch(["--heartbeat-only"])
        assert result == {"heartbeat_only": True}
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.get_next_batch.assert_not_called()

def test_run_dispatch_update_heartbeat():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {"batch_id": "batch_hb"}
    mock_hub_instance.get_queue_status.return_value = {}
    mock_hub_instance.generate_flash_status.return_value = {}

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch(["--phase", "27", "--milestone", "M27.1", "--update-heartbeat"])
        assert result["batch"] == {"batch_id": "batch_hb"}
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)

def test_run_dispatch_state_not_dict():
    # 辞書ではない場合
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="get_phase_state returned non-dict type"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_run_dispatch_phase_missing():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_milestone": "M27.1"
    }
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(KeyError, match="get_phase_state missing 'current_phase'"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_run_dispatch_phase_not_int():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": "twenty-seven",
        "current_milestone": "M27.1"
    }
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_phase must be a positive int"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_run_dispatch_milestone_missing():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27
    }
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(KeyError, match="get_phase_state missing 'current_milestone'"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_run_dispatch_milestone_not_str():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": 999
    }
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(TypeError, match="current_milestone must be a non-empty str"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_run_dispatch_invalid_batch_size():
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch(["--phase", "27", "--milestone", "M27.1", "--batch-size", "0"])

        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            run_dispatch(["--phase", "27", "--milestone", "M27.1", "--batch-size", "-5"])

def test_run_dispatch_next_batch_exception():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.side_effect = RuntimeError("Failed to fetch batch")
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Failed to fetch batch"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_called_once()

def test_run_dispatch_next_batch_returns_none():
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = None

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        result = run_dispatch([])
        assert result is None

def test_register_technical_debt_internal_exception(capsys):
    with patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", side_effect=Exception("Disk full")):
        register_technical_debt(pattern="test pattern", notes="test notes", line_number=42)
        captured = capsys.readouterr()
        assert "Failed to register technical debt: Disk full" in captured.err

def test_main_success(capsys):
    mock_result = {"batch": {"batch_id": "batch_abc"}}
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", return_value=mock_result):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 0
        captured = capsys.readouterr()
        assert "BATCH_START" in captured.out
        assert "batch_abc" in captured.out
        assert "BATCH_END" in captured.out

def test_main_returns_none(capsys):
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", return_value=None):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "No batch returned." in captured.err

def test_main_serialization_error(capsys):
    mock_result = {"batch": {1, 2, 3}}  # JSON serializable ではない set 型
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", return_value=mock_result):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "JSON serialization error" in captured.err

def test_main_exception(capsys):
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", side_effect=ValueError("Invalid phase")):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "Dispatch failed: Invalid phase" in captured.err

def test_register_technical_debt_success():
    mock_store_instance = MagicMock()
    with patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        register_technical_debt(pattern="test_pattern", notes="test_notes", line_number=42)
        mock_store_instance.register_debt.assert_called_once_with(
            category="MINOR_INFRA",
            file_path="agents/orchestration/dispatch_next_batch.py",
            line_number=42,
            pattern="test_pattern",
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリエーションを適用する",
            registered_by="sprint_thumbnail",
            notes="test_notes",
            tags=["dispatch_next_batch", "except_exception"]
        )

def test_run_dispatch_register_conversation_id_oserror():
    mock_hub_instance = MagicMock()
    mock_hub_instance.register_flash_conversation_id.side_effect = OSError("Disk write failed")
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(OSError, match="Disk write failed"):
            run_dispatch([])
        mock_store_instance.register_debt.assert_not_called()

def test_main_oserror(capsys):
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", side_effect=OSError("Disk full")):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "Dispatch failed due to I/O error" in captured.err
        assert "Dispatch failed: Disk full" in captured.err

def test_early_validation_conversation_id():
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        run_dispatch(["--conversation-id", ""])
    with pytest.raises(ValueError, match="conversation_id must be a non-empty string"):
        run_dispatch(["--conversation-id", "   "])

def test_early_validation_phase():
    with pytest.raises(ValueError, match="phase must be a positive integer"):
        run_dispatch(["--phase", "0"])
    with pytest.raises(ValueError, match="phase must be a positive integer"):
        run_dispatch(["--phase", "-5"])

def test_early_validation_milestone():
    with pytest.raises(ValueError, match="milestone must be a non-empty string"):
        run_dispatch(["--milestone", ""])
    with pytest.raises(ValueError, match="milestone must be a non-empty string"):
        run_dispatch(["--milestone", "   "])

def test_main_unexpected_exception_registers_debt():
    mock_store_instance = MagicMock()
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", side_effect=RuntimeError("Unexpected system failure")), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        mock_store_instance.register_debt.assert_called_once()

def test_early_validation_batch_size():
    # 無効な batch_size に対する早期バリデーション検証
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        run_dispatch(["--batch-size", "0"])
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        run_dispatch(["--batch-size", "-10"])

def test_run_dispatch_json_decode_error_during_registration():
    mock_hub_instance = MagicMock()
    # json.JSONDecodeError を模倣
    jde = json.JSONDecodeError("Expecting value", "", 0)
    mock_hub_instance.register_flash_conversation_id.side_effect = jde
    
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(json.JSONDecodeError, match="Expecting value"):
            run_dispatch([])

def test_run_dispatch_json_decode_error_during_heartbeat_only():
    mock_hub_instance = MagicMock()
    jde = json.JSONDecodeError("Expecting value", "", 0)
    mock_hub_instance.flash_update_heartbeat.side_effect = jde
    
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(json.JSONDecodeError, match="Expecting value"):
            run_dispatch(["--heartbeat-only"])

def test_run_dispatch_json_decode_error_during_phase_state():
    mock_hub_instance = MagicMock()
    jde = json.JSONDecodeError("Expecting value", "", 0)
    mock_hub_instance.get_phase_state.side_effect = jde
    
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        # phase と milestone が指定されていない場合に get_phase_state が呼ばれる
        with pytest.raises(json.JSONDecodeError, match="Expecting value"):
            run_dispatch([])

def test_run_dispatch_json_decode_error_during_get_next_batch():
    mock_hub_instance = MagicMock()
    jde = json.JSONDecodeError("Expecting value", "", 0)
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.side_effect = jde
    
    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(json.JSONDecodeError, match="Expecting value"):
            run_dispatch([])

def test_register_technical_debt_auto_line_number():
    mock_store_instance = MagicMock()
    with patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        # line_number を渡さずに呼び出す
        register_technical_debt(pattern="auto_pattern", notes="auto_notes")
        
        # 呼び出し時の行番号を特定する
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        
        # 渡された line_number が正の整数であることを検証
        assert called_kwargs["line_number"] > 0
        assert called_kwargs["pattern"] == "auto_pattern"
        assert called_kwargs["notes"] == "auto_notes"

def test_run_dispatch_invalid_arguments_raises_value_error():
    # 無効な引数を渡した時に ValueError が発生することを確認
    with pytest.raises(ValueError, match="Invalid command line arguments"):
        run_dispatch(["--invalid-argument-option"])

def test_main_json_decode_error(capsys):
    jde = json.JSONDecodeError("Expecting value", "", 0)
    with patch("backend.agents.orchestration.dispatch_next_batch.run_dispatch", side_effect=jde):
        with pytest.raises(SystemExit) as exit_info:
            main()
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "Dispatch failed due to JSON decode error" in captured.err
        assert "Expecting value" in captured.err

def test_register_technical_debt_exact_line_number_from_exception():
    # run_dispatch を実行して意図的に例外を発生させ、
    # register_technical_debt が正しい line_number (144付近) で呼び出されるか検証する
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.side_effect = RuntimeError("Mocked Hub Failure")
    mock_store_instance = MagicMock()

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.orchestration.dispatch_next_batch.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(RuntimeError, match="Mocked Hub Failure"):
            run_dispatch([])
        
        mock_store_instance.register_debt.assert_called_once()
        called_kwargs = mock_store_instance.register_debt.call_args.kwargs
        line_number = called_kwargs["line_number"]
        # dispatch_next_batch.py 内で get_next_batch は 156行目付近
        assert 140 <= line_number <= 165

def test_handle_hub_exceptions_class_name_logging(capsys):
    # TypeError が発生したときに、ログに Error (TypeError) が含まれるか検証する
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = TypeError("Invalid phase type")

    with patch("backend.agents.orchestration.dispatch_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(TypeError, match="Invalid phase type"):
            run_dispatch([])
        
        captured = capsys.readouterr()
        assert "Error (TypeError)" in captured.err


