import sys
import os
import importlib
from unittest.mock import MagicMock, patch
import pytest

# ルートパスを通す
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_scratch_get_next_batch_success(capsys):
    # すでにインポートされている場合はキャッシュを削除して再実行できるようにする
    if "scratch.get_next_batch" in sys.modules:
        del sys.modules["scratch.get_next_batch"]

    # OrchestrationHubのモック
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub.get_next_batch.return_value = {
        "batch_id": "test_batch_12345",
        "tasks": []
    }

    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        import scratch.get_next_batch

    captured = capsys.readouterr()
    assert "test_batch_12345" in captured.out
    
    mock_hub.get_phase_state.assert_called_once()
    mock_hub.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)


def test_scratch_get_next_batch_hub_exception():
    if "scratch.get_next_batch" in sys.modules:
        del sys.modules["scratch.get_next_batch"]

    mock_hub = MagicMock()
    mock_hub.get_phase_state.side_effect = Exception("Hub Error")

    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with pytest.raises(Exception) as excinfo:
            import scratch.get_next_batch
        assert "Hub Error" in str(excinfo.value)


def test_scratch_get_next_batch_state_none():
    if "scratch.get_next_batch" in sys.modules:
        del sys.modules["scratch.get_next_batch"]

    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = None

    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        with pytest.raises(ValueError) as excinfo:
            import scratch.get_next_batch
        assert "フェーズ状態の取得に失敗しました。" in str(excinfo.value)


def test_get_orchestration_hub():
    from scratch.get_next_batch import get_orchestration_hub
    with patch("scratch.get_next_batch.OrchestrationHub") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        res = get_orchestration_hub()
        assert res == mock_instance
        mock_class.assert_called_once()


def test_get_current_phase_info_success():
    from scratch.get_next_batch import get_current_phase_info
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    phase, milestone = get_current_phase_info(mock_hub)
    assert phase == 27
    assert milestone == "M27.1"
    mock_hub.get_phase_state.assert_called_once()


def test_get_current_phase_info_failure():
    from scratch.get_next_batch import get_current_phase_info
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = None
    with pytest.raises(ValueError) as excinfo:
        get_current_phase_info(mock_hub)
    assert "フェーズ状態の取得に失敗しました。" in str(excinfo.value)
    mock_hub.get_phase_state.assert_called_once()


def test_fetch_and_show_next_batch(capsys):
    from scratch.get_next_batch import fetch_and_show_next_batch
    mock_hub = MagicMock()
    mock_batch = {"batch_id": "test_batch_abc", "tasks": []}
    mock_hub.get_next_batch.return_value = mock_batch

    # デフォルトのbatch_size
    res = fetch_and_show_next_batch(mock_hub, 27, "M27.1")
    assert res == mock_batch
    mock_hub.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)
    captured = capsys.readouterr()
    assert "test_batch_abc" in captured.out

    # カスタムのbatch_size
    mock_hub.reset_mock()
    res = fetch_and_show_next_batch(mock_hub, 27, "M27.1", batch_size=3)
    assert res == mock_batch
    mock_hub.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=3)


def test_main():
    from scratch.get_next_batch import main
    mock_hub = MagicMock()
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub.get_next_batch.return_value = {"batch_id": "main_batch"}

    with patch("scratch.get_next_batch.OrchestrationHub", return_value=mock_hub):
        main()

    mock_hub.get_phase_state.assert_called_once()
    mock_hub.get_next_batch.assert_called_once_with(27, "M27.1", batch_size=6)

def test_direct_execution_module_error_resolved():
    # 直接実行したときに ModuleNotFoundError が発生しないことを確認する
    import subprocess
    res = subprocess.run(
        [sys.executable, "backend/scratch/get_next_batch.py"],
        capture_output=True,
        text=True
    )
    # 正常終了するか、または ValueError などの想定内エラーで終了することを確認
    assert res.returncode in (0, 1)
    assert "ModuleNotFoundError" not in res.stderr
