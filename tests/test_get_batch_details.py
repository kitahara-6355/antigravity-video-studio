import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# プロジェクトのルートパスを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration.get_batch_details import main

def test_get_batch_details_success(capsys):
    # OrchestrationHub をモック
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = [{
        "batch_id": "batch_mock123",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }]

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        main()

    # 標準出力を検証
    captured = capsys.readouterr()
    assert "Calling get_next_batch with phase=27, milestone=M27.1" in captured.out
    assert "BATCH_DETAILS:" in captured.out
    assert "batch_mock123" in captured.out

    # モックのメソッドが正しく呼び出されたことを確認
    mock_hub_instance.get_phase_state.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)

def test_get_batch_details_state_none(capsys):
    # get_phase_state が None を返すケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error:" in captured.err or "Failed" in captured.err

def test_get_batch_details_key_missing(capsys):
    # キーが欠損している（または None）ケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": None,
        "current_milestone": None
    }

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error:" in captured.err or "Failed" in captured.err

def test_get_batch_details_exception(capsys):
    # OrchestrationHub が例外を投げるケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("OrchestrationHub connection failure")

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error:" in captured.err or "Failed" in captured.err

def test_get_batch_details_main_execution(capsys):
    import runpy
    # runpy を使って __main__ として実行する
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = [{
        "batch_id": "batch_mock123",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }]

    # OrchestrationHub をパッチしつつ run_path を実行する
    target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend/agents/orchestration/get_batch_details.py"))
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        runpy.run_path(target_path, run_name="__main__")

    # 標準出力を検証
    captured = capsys.readouterr()
    assert "Calling get_next_batch with phase=27, milestone=M27.1" in captured.out
    assert "BATCH_DETAILS:" in captured.out
    assert "batch_mock123" in captured.out

def test_get_batch_details_different_cwd(capsys):
    import runpy
    import os
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = [{
        "batch_id": "batch_mock123",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }]

    target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend/agents/orchestration/get_batch_details.py"))
    
    original_cwd = os.getcwd()
    temp_cwd = os.path.dirname(__file__)
    
    try:
        os.chdir(temp_cwd)
        if "backend.agents.orchestration.get_batch_details" in sys.modules:
            del sys.modules["backend.agents.orchestration.get_batch_details"]
            
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(target_path, run_name="__main__")
    finally:
        os.chdir(original_cwd)

    captured = capsys.readouterr()
    assert "Calling get_next_batch with phase=27, milestone=M27.1" in captured.out
    assert "BATCH_DETAILS:" in captured.out
    assert "batch_mock123" in captured.out


def test_get_batch_details_file_not_found_exception(capsys):
    # テストの実行順に依存せず、常に最新のモジュールからメイン関数をロードする
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = FileNotFoundError("State file not found")

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: File access error:" in captured.err


def test_get_batch_details_json_decode_exception(capsys):
    from backend.agents.orchestration.get_batch_details import main
    import json
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = json.JSONDecodeError("Expecting value", "{}", 0)

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Failed to parse JSON configuration:" in captured.err


def test_get_batch_details_quota_exceeded_exception(capsys):
    from backend.agents.orchestration.get_batch_details import main
    from backend.agents.orchestration.hub_common import OpusQuotaExceededException
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = OpusQuotaExceededException("Quota exceeded")

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Opus quota exceeded:" in captured.err


def test_get_batch_details_value_error_exception(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = ValueError("Invalid value in config")

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Invalid configuration or missing keys:" in captured.err


def test_get_batch_details_runtime_error_exception(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Something went wrong")

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Runtime error during batch details retrieval:" in captured.err


def test_get_batch_details_state_not_dict(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = ["not", "a", "dict"]

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Invalid configuration or missing keys:" in captured.err


def test_get_batch_details_phase_not_int(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": "not_an_int",
        "current_milestone": "M27.1"
    }

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Invalid configuration or missing keys:" in captured.err


def test_get_batch_details_milestone_not_str(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": 123  # not a string
    }

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Invalid configuration or missing keys:" in captured.err


def test_get_batch_details_batch_not_list(capsys):
    from backend.agents.orchestration.get_batch_details import main
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub_instance.get_next_batch.return_value = "not_a_list"

    with patch("backend.agents.orchestration.get_batch_details.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "Error: Invalid configuration or missing keys:" in captured.err

