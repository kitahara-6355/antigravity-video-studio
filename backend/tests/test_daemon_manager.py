import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.agents.orchestration.daemon_manager import DaemonConfig, DaemonManager

def test_daemon_config_default():
    """デフォルト設定で DaemonConfig が作成できることを確認"""
    config = DaemonConfig()
    assert config.max_restart_attempts == 3
    assert config.restart_backoff_base == 10.0
    assert config.health_check_interval == 5

def test_daemon_config_validation():
    """不正な値に対してバリデーションが動作することを確認"""
    # 正常系
    config = DaemonConfig(max_restart_attempts=5)
    assert config.max_restart_attempts == 5

    # 異常系: pid_file が Path でない
    with pytest.raises(TypeError):
        DaemonConfig(pid_file="not_a_path")  # type: ignore

    # 異常系: log_dir が Path でない
    with pytest.raises(TypeError):
        DaemonConfig(log_dir="not_a_path")  # type: ignore

    # 異常系: max_restart_attempts が負
    with pytest.raises(ValueError):
        DaemonConfig(max_restart_attempts=-1)

    # 異常系: max_restart_attempts が int でない
    with pytest.raises(ValueError):
        DaemonConfig(max_restart_attempts=1.5)  # type: ignore

    # 異常系: restart_backoff_base が 0 以下
    with pytest.raises(ValueError):
        DaemonConfig(restart_backoff_base=0.0)

    # 異常系: health_check_interval が 0 以下
    with pytest.raises(ValueError):
        DaemonConfig(health_check_interval=0)

    # 異常系: memory_leak_check_interval が 0 以下
    with pytest.raises(ValueError):
        DaemonConfig(memory_leak_check_interval=0)

    # 異常系: memory_leak_threshold が 0 以下
    with pytest.raises(ValueError):
        DaemonConfig(memory_leak_threshold=-0.5)

def test_daemon_manager_lifecycle(safe_popen_mock, tmp_path):
    """DaemonManager のライフサイクル (start/stop) が正常に動作することを確認"""
    pid_file = tmp_path / "test.pid"
    log_dir = tmp_path / "logs"
    config = DaemonConfig(
        pid_file=pid_file,
        log_dir=log_dir,
        max_restart_attempts=1,
        health_check_interval=1,
    )
    
    manager = DaemonManager(config=config)
    
    mock_proc = safe_popen_mock(returncode=0)
    mock_proc.pid = 9999
    
    with patch("subprocess.Popen", return_value=mock_proc):
        # 起動
        pid = manager.start()
        assert pid == 9999
        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == "9999"
        
        # 停止
        stopped = manager.stop()
        assert stopped is True
        assert not pid_file.exists()
