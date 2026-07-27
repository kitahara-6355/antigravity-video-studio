import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# ルートパスを通す
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

@pytest.fixture(autouse=True)
def clean_sys_modules_and_path():
    # テスト開始前の状態を保存
    original_path = list(sys.path)
    
    # 対象モジュールのキャッシュを削除
    sys.modules.pop("backend.scratch.update_heartbeat", None)
    sys.modules.pop("scratch.update_heartbeat", None)
    
    yield
    
    # テスト終了後に復元
    sys.path = original_path
    sys.modules.pop("backend.scratch.update_heartbeat", None)
    sys.modules.pop("scratch.update_heartbeat", None)

def test_update_heartbeat_success(capsys):
    mock_hub = MagicMock()
    # backend.agents.orchestration.OrchestrationHub を mock
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub) as mock_class:
        # モジュールをインポートして実行
        import backend.scratch.update_heartbeat
        
        # 検証
        mock_class.assert_called_once()
        mock_hub.flash_update_heartbeat.assert_called_once()
        captured = capsys.readouterr()
        assert "Heartbeat updated successfully." in captured.out

def test_update_heartbeat_failure():
    mock_hub = MagicMock()
    mock_hub.flash_update_heartbeat.side_effect = RuntimeError("Failed to update")
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        # インポート時に実行されて例外が発生することを確認
        with pytest.raises(RuntimeError, match="Failed to update"):
            import backend.scratch.update_heartbeat

def test_update_heartbeat_direct_execution(capsys):
    # runpy.run_path を使ってスクリプトとして直接実行するテスト
    mock_hub = MagicMock()
    filepath = os.path.abspath(os.path.join(PROJECT_ROOT, "scratch/update_heartbeat.py"))
    
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
        import runpy
        # runpy.run_path は __name__ を "__main__" にしてスクリプトを実行する
        runpy.run_path(filepath, run_name="__main__")
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        captured = capsys.readouterr()
        assert "Heartbeat updated successfully." in captured.out


def test_update_heartbeat_sys_path_insertion():
    mock_hub = MagicMock()
    target_path = 'C:/Users/PC_User/Desktop/script/video-automation'
    if target_path in sys.path:
        sys.path.remove(target_path)
    with patch('backend.agents.orchestration.OrchestrationHub', return_value=mock_hub):
        import sys as sys_mod
        sys_mod.modules.pop('backend.scratch.update_heartbeat', None)
        import backend.scratch.update_heartbeat
        assert sys_mod.path[0] == target_path
