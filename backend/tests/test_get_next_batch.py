import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# プロジェクトのルートパスを sys.path に追加して、backend/scratch/get_next_batch.py がインポートできるようにする
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.scratch.get_next_batch import main

def test_get_next_batch_success(capsys):
    # OrchestrationHub をモック
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "batch_aa4249",
        "tasks": [{"task_id": "T-1", "status": "pending"}]
    }
    mock_hub_instance.get_queue_status.return_value = {
        "pending": 1,
        "running": 0
    }

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    # 標準出力を検証
    captured = capsys.readouterr()
    assert "Current Phase: 26, Milestone: M26.1" in captured.out
    assert "Next batch:" in captured.out
    assert "batch_aa4249" in captured.out
    assert "Queue status after get_next_batch:" in captured.out

    # モックのメソッドが正しく呼び出されたことを確認
    mock_hub_instance.get_phase_state.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once_with(26, "M26.1", batch_size=4)
    mock_hub_instance.get_queue_status.assert_called_once()

def test_get_next_batch_exception(capsys):
    # OrchestrationHub が例外を投げるケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Simulated connection failure")

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    # 標準出力を検証
    captured = capsys.readouterr()
    assert "Error: Simulated connection failure" in captured.out


def test_get_next_batch_validation_error_none(capsys):
    # state is None のケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = None

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    captured = capsys.readouterr()
    assert "Validation Error: Phase state is None" in captured.out

def test_get_next_batch_validation_error_type(capsys):
    # state が辞書型でないケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = ["not", "a", "dictionary"]

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    captured = capsys.readouterr()
    assert "Validation Error: Phase state is not a dictionary" in captured.out

def test_get_next_batch_validation_error_missing_phase(capsys):
    # current_phase キーが欠損しているケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_milestone": "M26.1"
    }

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    captured = capsys.readouterr()
    assert "Validation Error: 'current_phase' key is missing in phase state" in captured.out

def test_get_next_batch_validation_error_missing_milestone(capsys):
    # current_milestone キーが欠損しているケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26
    }

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        main()

    captured = capsys.readouterr()
    assert "Validation Error: 'current_milestone' key is missing in phase state" in captured.out


def test_get_next_batch_name_based_branching_non_backend(capsys):
    # __name__ が backend. から始まらない場合の挙動確認
    # この場合、例外がキャッチされずに上に抜けるはず
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Original Branch Error")

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.scratch.get_next_batch.__name__", "scratch.get_next_batch"):
            with pytest.raises(RuntimeError) as excinfo:
                main()
            assert "Original Branch Error" in str(excinfo.value)
