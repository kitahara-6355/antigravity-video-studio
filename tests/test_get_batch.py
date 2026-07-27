import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# プロジェクトのルートパスを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_get_batch_import_only():
    # インポート時に OrchestrationHub や os.remove が呼ばれないことを確認
    with patch("backend.agents.orchestration.get_batch.OrchestrationHub") as mock_hub,          patch("backend.agents.orchestration.get_batch.os.remove") as mock_remove:
        
        # すでにインポートされている場合は一旦削除
        if "backend.agents.orchestration.get_batch" in sys.modules:
            del sys.modules["backend.agents.orchestration.get_batch"]
            
        import backend.agents.orchestration.get_batch
        
        mock_hub.assert_not_called()
        mock_remove.assert_not_called()

def test_get_batch_main_success(capsys):
    from backend.agents.orchestration.get_batch import main

    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "test_batch_123",
        "tasks": []
    }

    with patch("backend.agents.orchestration.get_batch.OrchestrationHub", return_value=mock_hub_instance),          patch("backend.agents.orchestration.get_batch.os.remove") as mock_remove:
        
        main()

        captured = capsys.readouterr()
        assert "===BATCH===" in captured.out
        assert "test_batch_123" in captured.out
        
        mock_hub_instance.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=6)
        mock_remove.assert_called_once()

def test_get_batch_main_exception(capsys):
    from backend.agents.orchestration.get_batch import main

    mock_hub_instance = MagicMock()
    mock_hub_instance.get_next_batch.side_effect = RuntimeError("Mock DB Error")

    with patch("backend.agents.orchestration.get_batch.OrchestrationHub", return_value=mock_hub_instance),          patch("backend.agents.orchestration.get_batch.os.remove") as mock_remove:
        
        with pytest.raises(SystemExit) as excinfo:
            main()
        
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Mock DB Error" in captured.err
        mock_remove.assert_not_called()
