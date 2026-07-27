import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

class TestMarkTasksP27Multi2(unittest.TestCase):
    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"status": "success"}
        
        # main を呼ぶために、テスト実行時にインポートする
        from backend.agents.orchestration.mark_tasks_p27_multi2 import main
        
        with patch('builtins.print') as mock_print:
            main()
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("a9736a64-a242-485f-942e-bf8476d21fa6")
            mock_hub.flash_update_heartbeat.assert_called_once()
            
            self.assertEqual(mock_hub.mark_task_done.call_count, 2)
            mock_hub.mark_task_done.assert_any_call("T-batch_a97ee3-refactor-000", "pass", {
                "message": "agents/orchestration/atomic_io.py のデッドコード除去・関数分割・テスト追加。",
                "changed_files": [
                    "backend/agents/orchestration/atomic_io.py",
                    "backend/tests/test_atomic_io.py"
                ]
            })
            mock_hub.mark_task_done.assert_any_call("T-batch_a97ee3-thumbnail-000", "pass", {
                "message": "verify_thumbnail_gen.py のサムネイル処理改善と品質検証・テスト追加。",
                "changed_files": [
                    "backend/agents/council_graph.py",
                    "backend/tests/phase2_validator.py"
                ]
            })
            
            mock_hub.generate_flash_status.assert_called_once()
            mock_print.assert_any_call("TASKS_MARKED_DONE")
            mock_print.assert_any_call('FLASH_STATUS:{"status": "success"}')

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        mock_hub_class.return_value = mock_hub
        
        script_path = str(backend_dir / 'agents' / 'orchestration' / 'mark_tasks_p27_multi2.py')
        with patch('builtins.print'):
            try:
                runpy.run_path(script_path, run_name='__main__')
            except SystemExit as e:
                self.assertEqual(e.code, 0)
            
        mock_hub_class.assert_called_once()

    @patch('backend.agents.orchestration.mark_tasks_p27_multi2.OrchestrationHub')
    def test_main_exception_handling(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.flash_update_heartbeat.side_effect = RuntimeError("Mocked connection error")
        
        from backend.agents.orchestration.mark_tasks_p27_multi2 import main
        
        with patch('sys.stderr') as mock_stderr:
            result = main()
            self.assertEqual(result, 1)
            mock_stderr.write.assert_called()

if __name__ == '__main__':
    unittest.main()
