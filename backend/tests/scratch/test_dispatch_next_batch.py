import sys
import os
import runpy
from unittest.mock import patch, MagicMock
import pytest

# 親ディレクトリ（video-automation）を sys.path に追加して、
# backend.agents.orchestration パッケージが正しくインポートできるようにする
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_dispatch_next_batch_success(capsys):
    original_path = list(sys.path)
    
    # キャッシュされたモジュールがあれば削除（実行のたびに再ロードされるようにする）
    sys.modules.pop("backend.scratch.dispatch_next_batch", None)
    
    # OrchestrationHub のモック化
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26,
        "current_milestone": "M26.1"
    }
    mock_hub_instance.get_next_batch.return_value = {
        "batch_id": "test_batch_123",
        "tasks": []
    }
    
    target_module = "backend.scratch.dispatch_next_batch"
    
    # OrchestrationHub 自体をモック化
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(target_module, run_name="__main__")
        assert excinfo.value.code == 0
        
    # 標準出力を取得
    captured = capsys.readouterr()
    
    assert "BATCH_START" in captured.out
    assert "BATCH_END" in captured.out
    assert "test_batch_123" in captured.out
    
    # sys.path に親ディレクトリとbackendディレクトリが含まれていることを確認
    assert project_root in sys.path
    backend_path = os.path.join(project_root, "backend")
    assert backend_path in sys.path
    
    # sys.path を元に戻す
    sys.path = original_path

def test_dispatch_next_batch_error(capsys):
    original_path = list(sys.path)
    
    # キャッシュされたモジュールがあれば削除
    sys.modules.pop("backend.scratch.dispatch_next_batch", None)
    
    # OrchestrationHub のモック化でエラーを発生させる
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.side_effect = RuntimeError("Mocked connection error")
    
    target_module = "backend.scratch.dispatch_next_batch"
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(target_module, run_name="__main__")
        assert excinfo.value.code == 1
            
    # 標準エラー出力を確認
    captured = capsys.readouterr()
    assert "Error executing dispatch_next_batch" in captured.err
    assert "RuntimeError: Mocked connection error" in captured.err

    # sys.path を元に戻す
    sys.path = original_path

def test_dispatch_next_batch_key_error(capsys):
    original_path = list(sys.path)
    
    # キャッシュされたモジュールがあれば削除
    sys.modules.pop("backend.scratch.dispatch_next_batch", None)
    
    # OrchestrationHub のモック化で KeyError を発生させる (milestoneが無い)
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_phase_state.return_value = {
        "current_phase": 26
    }
    
    target_module = "backend.scratch.dispatch_next_batch"
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(target_module, run_name="__main__")
        assert excinfo.value.code == 1
            
    # 標準エラー出力を確認
    captured = capsys.readouterr()
    assert "Error executing dispatch_next_batch" in captured.err
    assert "KeyError" in captured.err

    # sys.path を元に戻す
    sys.path = original_path


def test_dispatch_next_batch_unexpected_error_registers_debt(capsys):
    original_path = list(sys.path)
    
    # キャッシュされたモジュールがあれば削除
    sys.modules.pop("backend.scratch.dispatch_next_batch", None)
    
    # OrchestrationHub のモック化
    mock_hub_instance = MagicMock()
    # 予期せぬ例外（例：TypeError）を発生させる
    mock_hub_instance.get_phase_state.side_effect = TypeError("Unexpected parameter type")
    
    mock_store_instance = MagicMock()
    
    target_module = "backend.scratch.dispatch_next_batch"
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(target_module, run_name="__main__")
        assert excinfo.value.code == 1
            
    # 標準エラー出力を確認
    captured = capsys.readouterr()
    assert "Unexpected error executing dispatch_next_batch" in captured.err
    assert "TypeError: Unexpected parameter type" in captured.err
    
    # 技術負債が登録されたことを検証
    mock_store_instance.register_debt.assert_called_once()
    kwargs = mock_store_instance.register_debt.call_args.kwargs
    assert kwargs["category"] == "MINOR_INFRA"
    assert kwargs["pattern"] == "dispatch_next_batch.main"
    assert "Unexpected parameter type" in kwargs["notes"]

    # sys.path を元に戻す
    sys.path = original_path


def test_dispatch_next_batch_technical_debt_registration_failure(capsys):
    original_path = list(sys.path)
    
    # キャッシュされたモジュールがあれば削除
    sys.modules.pop("backend.scratch.dispatch_next_batch", None)
    
    # OrchestrationHub のモック化
    mock_hub_instance = MagicMock()
    # 予期せぬ例外（例：TypeError）を発生させる
    mock_hub_instance.get_phase_state.side_effect = TypeError("Unexpected parameter type")
    
    # TechnicalDebtStore の register_debt で例外を発生させる
    mock_store_instance = MagicMock()
    mock_store_instance.register_debt.side_effect = Exception("Database disk full")
    
    target_module = "backend.scratch.dispatch_next_batch"
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_instance):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module(target_module, run_name="__main__")
        assert excinfo.value.code == 1
            
    # 標準エラー出力を確認
    captured = capsys.readouterr()
    assert "Failed to register technical debt: Database disk full" in captured.err
    assert "Unexpected error executing dispatch_next_batch" in captured.err

    # sys.path を元に戻す
    sys.path = original_path



