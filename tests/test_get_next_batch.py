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
    assert "batch_aa4249" in captured.out
    assert "Queue status after get_next_batch:" in captured.out

    # モックのメソッドが正しく呼び出されたことを確認
    mock_hub_instance.get_phase_state.assert_called_once()
    mock_hub_instance.get_next_batch.assert_called_once_with(26, "M26.1", batch_size=6)
    mock_hub_instance.get_queue_status.assert_called_once()

def test_get_next_batch_exception(capsys):
    # OrchestrationHub が例外を投げるケース
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Simulated connection failure")

    with patch("backend.scratch.get_next_batch.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(RuntimeError) as excinfo:
            main()
    assert "Simulated connection failure" in str(excinfo.value)
