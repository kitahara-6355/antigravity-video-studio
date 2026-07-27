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

class TestMarkTasksP27Multi10(unittest.TestCase):
    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        
        # main を呼ぶために、テスト実行時にインポートする
        from backend.agents.orchestration.mark_tasks_p27_multi10 import main
        
        with patch('builtins.print') as mock_print:
            main()
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
            mock_hub.flash_update_heartbeat.assert_called_once()
            
            self.assertEqual(mock_hub.mark_task_done.call_count, 2)
            mock_hub.mark_task_done.assert_any_call(
                "T-batch_3f4c3a-test_weaver-000",
                "pass",
                {
                    "subagent_id": "2a387bbf-fac8-400f-a0d8-c952067e6a5b",
                    "message": "philosophy_manager.py テストカバレッジ改善タスク完了報告。カバレッジ 94% -> 100% (+6%)",
                    "changed_files": ["backend/tests/test_philosophy_manager.py"]
                }
            )
            mock_hub.mark_task_done.assert_any_call(
                "T-batch_3f4c3a-bug_hunter-000",
                "pass",
                {
                    "subagent_id": "bc2ee7da-e9ba-48ec-acee-3dd79c3616f0",
                    "message": "heartbeat_only.py バグ修正タスク完了。引数混入によるテストFAILをargv引数のオプショナル化で修正",
                    "changed_files": [
                        "backend/agents/orchestration/heartbeat_only.py",
                        "backend/tests/test_heartbeat_only.py"
                    ]
                }
            )
            
            mock_hub.generate_flash_status.assert_called_once()
            mock_print.assert_any_call("Marked T-batch_3f4c3a-test_weaver-000 as pass.")
            mock_print.assert_any_call("Marked T-batch_3f4c3a-bug_hunter-000 as pass.")
            mock_print.assert_any_call("=== STATUS ===")
            mock_print.assert_any_call("mocked_status")
            mock_print.assert_any_call("==============")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        mock_hub_class.return_value = mock_hub
        
        script_path = str(project_root / 'backend' / 'agents' / 'orchestration' / 'mark_tasks_p27_multi10.py')
        with patch('builtins.print'):
            runpy.run_path(script_path, run_name='__main__')
            
        mock_hub_class.assert_called_once()

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_exception_handling(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub.flash_update_heartbeat.side_effect = Exception("Mocked connection error")
        mock_hub_class.return_value = mock_hub
        
        # reload or import main
        import importlib
        import backend.agents.orchestration.mark_tasks_p27_multi10
        importlib.reload(backend.agents.orchestration.mark_tasks_p27_multi10)
        from backend.agents.orchestration.mark_tasks_p27_multi10 import main
        
        with patch('sys.exit') as mock_exit, patch('builtins.print') as mock_print:
            main()
            mock_exit.assert_called_once_with(1)
            mock_print.assert_any_call("Error in mark_tasks_p27_multi10: Mocked connection error", file=sys.stderr)

if __name__ == '__main__':
    unittest.main()

