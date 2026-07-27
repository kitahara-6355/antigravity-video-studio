import sys
import pytest
import runpy
from unittest.mock import MagicMock, patch

# テスト対象モジュールをインポート
import backend.agents.orchestration.submit_and_next as submit_and_next

def test_main_insufficient_arguments(capsys):
    """引数が足りない場合 (引数1つのみ) に sys.exit(1) と Usage が出力されることを検証"""
    test_args = ["submit_and_next.py"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            submit_and_next.main()
        
        # exit code が 1 であることを確認
        assert exc_info.value.code == 1
        
        # Usage が出力されたことを確認
        captured = capsys.readouterr()
        assert "Usage: python submit_and_next.py" in captured.out

def test_main_insufficient_arguments_only_one_param(capsys):
    """引数が1つだけ足りない場合 (合計2個) に sys.exit(1) と Usage が出力されることを検証"""
    test_args = ["submit_and_next.py", "conv_id"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(SystemExit) as exc_info:
            submit_and_next.main()
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: python submit_and_next.py" in captured.out

@patch("backend.agents.orchestration.submit_and_next.OrchestrationHub")
def test_main_success_default_values(mock_hub_class, capsys):
    """引数が2つの場合 (デフォルト値が適用される) の正常系フローを検証"""
    # OrchestrationHub のモックインスタンスの設定
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub.get_next_batch.return_value = {"tasks": []}
    mock_hub.generate_flash_status.return_value = {
        "formatted": "Mocked Status"
    }
    
    test_args = ["submit_and_next.py", "conv123", "batch456"]
    with patch.object(sys, 'argv', test_args):
        submit_and_next.main()
        
        # 呼び出しの検証
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("conv123")
        mock_hub.flash_update_heartbeat.assert_called_once()
        
        # submit_batch_report の引数検証 (デフォルト passed=8, failed=0)
        expected_results = {
            "passed": 8,
            "failed": 0,
            "skipped": 0,
            "total": 8
        }
        mock_hub.submit_batch_report.assert_called_once_with("batch456", expected_results)
        
        # get_phase_state, get_next_batch, generate_flash_status の検証
        mock_hub.get_phase_state.assert_called_once()
        mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=6)
        mock_hub.generate_flash_status.assert_called_once()
        
        # 出力の検証
        captured = capsys.readouterr()
        assert "Batch batch456 submitted." in captured.out
        assert "=== NEW BATCH ===" in captured.out
        assert "=== STATUS ===" in captured.out
        assert "Mocked Status" in captured.out

@patch("backend.agents.orchestration.submit_and_next.OrchestrationHub")
def test_main_success_custom_values(mock_hub_class, capsys):
    """引数が4つの場合 (カスタム値が適用される) の正常系フローを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {}  # 空の場合、デフォルト値 27, "M27.1" が使われるはず
    mock_hub.get_next_batch.return_value = {"tasks": ["task1"]}
    mock_hub.generate_flash_status.return_value = {
        "formatted": "Custom Mocked Status"
    }
    
    test_args = ["submit_and_next.py", "conv123", "batch456", "10", "2"]
    with patch.object(sys, 'argv', test_args):
        submit_and_next.main()
        
        # submit_batch_report の引数検証 (passed=10, failed=2)
        expected_results = {
            "passed": 10,
            "failed": 2,
            "skipped": 0,
            "total": 12
        }
        mock_hub.submit_batch_report.assert_called_once_with("batch456", expected_results)
        
        # get_next_batch がデフォルトの phase=27, milestone="M27.1" で呼ばれることの検証
        mock_hub.get_next_batch.assert_called_once_with(phase=27, milestone="M27.1", batch_size=6)
        
        captured = capsys.readouterr()
        assert "Batch batch456 submitted." in captured.out
        assert "Custom Mocked Status" in captured.out

def test_main_as_script():
    """__name__ == '__main__' のブロックをカバーするために runpy を使ってスクリプト実行する"""
    test_args = ["submit_and_next.py", "conv123", "batch456"]
    
    with patch.object(sys, 'argv', test_args):
        # runpy 内でのインポート解決に合わせて backend.agents.orchestration.OrchestrationHub をモック
        with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
            mock_hub = mock_hub_class.return_value
            mock_hub.get_phase_state.return_value = {
                "current_phase": 27,
                "current_milestone": "M27.1"
            }
            mock_hub.get_next_batch.return_value = {"tasks": []}
            mock_hub.generate_flash_status.return_value = {
                "formatted": "Mocked Status"
            }
            
            # runpy.run_module を使って submit_and_next をスクリプトとして直接実行
            runpy.run_module("backend.agents.orchestration.submit_and_next", run_name="__main__")
            
            # 各呼び出しの検証
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("conv123")
            mock_hub.flash_update_heartbeat.assert_called_once()
            
            expected_results = {
                "passed": 8,
                "failed": 0,
                "skipped": 0,
                "total": 8
            }
            mock_hub.submit_batch_report.assert_called_once_with("batch456", expected_results)


@patch("backend.agents.orchestration.submit_and_next.OrchestrationHub")
def test_main_success_three_arguments(mock_hub_class, capsys):
    """引数が3つの場合 (failedはデフォルト値が適用される) の正常系フローを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub.get_next_batch.return_value = {"tasks": []}
    mock_hub.generate_flash_status.return_value = {
        "formatted": "Mocked Status"
    }
    
    test_args = ["submit_and_next.py", "conv123", "batch456", "5"]
    with patch.object(sys, 'argv', test_args):
        submit_and_next.main()
        
        # submit_batch_report の引数検証 (passed=5, failed=0)
        expected_results = {
            "passed": 5,
            "failed": 0,
            "skipped": 0,
            "total": 5
        }
        mock_hub.submit_batch_report.assert_called_once_with("batch456", expected_results)

@patch("backend.agents.orchestration.submit_and_next.OrchestrationHub")
def test_main_too_many_arguments(mock_hub_class, capsys):
    """引数が5つ以上（余分な引数がある）の場合の動作を検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = {
        "current_phase": 27,
        "current_milestone": "M27.1"
    }
    mock_hub.get_next_batch.return_value = {"tasks": []}
    mock_hub.generate_flash_status.return_value = {
        "formatted": "Mocked Status"
    }
    
    test_args = ["submit_and_next.py", "conv123", "batch456", "10", "2", "extra_argument"]
    with patch.object(sys, 'argv', test_args):
        submit_and_next.main()
        
        # submit_batch_report の引数検証 (passed=10, failed=2)
        expected_results = {
            "passed": 10,
            "failed": 2,
            "skipped": 0,
            "total": 12
        }
        mock_hub.submit_batch_report.assert_called_once_with("batch456", expected_results)

def test_main_invalid_passed_argument():
    """passed引数が整数に変換できない場合に ValueError が発生することを検証"""
    test_args = ["submit_and_next.py", "conv123", "batch456", "invalid_num"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(ValueError):
            submit_and_next.main()

def test_main_invalid_failed_argument():
    """failed引数が整数に変換できない場合に ValueError が発生することを検証"""
    test_args = ["submit_and_next.py", "conv123", "batch456", "10", "invalid_num"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(ValueError):
            submit_and_next.main()

@patch("backend.agents.orchestration.submit_and_next.OrchestrationHub")
def test_main_hub_get_phase_state_none(mock_hub_class):
    """get_phase_state が None を返す場合に AttributeError が発生することを検証"""
    mock_hub = mock_hub_class.return_value
    mock_hub.get_phase_state.return_value = None
    
    test_args = ["submit_and_next.py", "conv123", "batch456"]
    with patch.object(sys, 'argv', test_args):
        with pytest.raises(AttributeError):
            submit_and_next.main()
