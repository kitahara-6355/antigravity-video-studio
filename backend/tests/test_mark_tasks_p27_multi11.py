import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# プロジェクトルートと backend ディレクトリを sys.path に追加
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / 'backend') not in sys.path:
    sys.path.insert(0, str(project_root / 'backend'))

class TestMarkTasksP27Multi11(unittest.TestCase):
    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        
        # main を呼ぶために、テスト実行時にインポートする
        from backend.agents.orchestration.mark_tasks_p27_multi11 import main
        
        with patch('builtins.print') as mock_print:
            main()
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
            mock_hub.flash_update_heartbeat.assert_called_once()
            
            mock_hub.mark_task_done.assert_called_once_with(
                "T-batch_3f4c3a-test_weaver-001",
                "pass",
                {
                    "subagent_id": "029ca7ab-fdf5-41d4-96e2-a1cb199fa174",
                    "message": "tests/scratch/migrate_e2e_files.py テストカバレッジ改善完了。例外処理カバレッジを追加し100%に向上",
                    "changed_files": ["backend/tests/scratch/test_migrate_e2e_files.py"]
                }
            )
            
            mock_hub.generate_flash_status.assert_called_once()
            mock_print.assert_any_call("Marked T-batch_3f4c3a-test_weaver-001 as pass.")
            mock_print.assert_any_call("=== STATUS ===")
            mock_print.assert_any_call("mocked_status")
            mock_print.assert_any_call("==============")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        mock_hub_class.return_value = mock_hub
        
        script_path = str(project_root / 'backend' / 'agents' / 'orchestration' / 'mark_tasks_p27_multi11.py')
        with patch('builtins.print'):
            runpy.run_path(script_path, run_name='__main__')
            
        mock_hub_class.assert_called_once()

if __name__ == '__main__':
    unittest.main()
