import pytest
import os
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from backend.agents.orchestration.resource_governor import ResourceGovernor
from backend.agents.orchestration.hub_batch import BatchMixin

# ゾンビパージのテスト
def test_kill_zombie_test_processes():
    governor = ResourceGovernor()
    
    # 実際には他のプロセスを強制終了させないために、psutil.process_iter をモック化する
    with patch("psutil.process_iter") as mock_iter:
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 99999,
            'name': 'pytest',
            'cmdline': ['pytest', 'some_test.py'],
            'create_time': time.time() - 200 # 180秒超
        }
        mock_iter.return_value = [mock_proc]
        
        killed = governor.kill_zombie_test_processes(timeout_seconds=180.0)
        
        assert killed == 1
        mock_proc.kill.assert_called_once()

# アサイン前診断のテスト
class DummyOrchestrator(BatchMixin):
    def __init__(self):
        pass

def test_is_module_eligible():
    orchestrator = DummyOrchestrator()
    
    # ダミーのカバレッジデータ
    coverage_data = {
        "files": {
            "backend/services/eligible.py": {
                "summary": {"percent_covered": 50.0},
                "missing_lines": [10, 11]
            },
            "backend/services/full_covered.py": {
                "summary": {"percent_covered": 100.0},
                "missing_lines": []
            }
        }
    }
    
    # openなTDRファイル
    open_tdr_files = {"services/eligible_tdr.py"}
    
    # test_weaverの場合
    # カバレッジ100%は不適格
    assert orchestrator._is_module_eligible("test_weaver", "services/eligible.py", coverage_data, open_tdr_files) is True
    assert orchestrator._is_module_eligible("test_weaver", "services/full_covered.py", coverage_data, open_tdr_files) is False
    
    # tdr_cleanupの場合
    # openなTDRがあれば適格
    assert orchestrator._is_module_eligible("tdr_cleanup", "services/eligible_tdr.py", coverage_data, open_tdr_files) is True
    assert orchestrator._is_module_eligible("tdr_cleanup", "services/no_tdr.py", coverage_data, open_tdr_files) is False
