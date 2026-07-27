import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.agents.orchestration.mark_tasks_p27_multi6 import (
    main,
    create_and_register_hub,
    update_hub_heartbeat,
    mark_task_failure,
    log_task_failure_completion,
    process_task_failure_pipeline,
    display_latest_status,
)

class TestMarkTasksP27Multi6(unittest.TestCase):
    @patch('backend.agents.orchestration.mark_tasks_p27_multi6.OrchestrationHub')
    def test_main(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {'formatted': 'mock_status'}
        mock_hub_class.return_value = mock_hub
        
        with patch('builtins.print') as mock_print:
            main()
            
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with('3ed8fce0-a204-47fd-a220-c27fecf03706')
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            'T-batch_c4f4d2-thumbnail-001', 
            'fail', 
            {'error': 'RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model.'}
        )
        mock_hub.generate_flash_status.assert_called_once()
        
        mock_print.assert_any_call('TASK_MARKED_FAIL')
        mock_print.assert_any_call('=== STATUS ===')
        mock_print.assert_any_call('mock_status')
        mock_print.assert_any_call('==============')

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {'formatted': 'mock_status'}
        mock_hub_class.return_value = mock_hub
        
        script_path = Path(__file__).resolve().parent.parent / 'agents' / 'orchestration' / 'mark_tasks_p27_multi6.py'
        with patch('builtins.print'):
            runpy.run_path(str(script_path), run_name='__main__')
        mock_hub_class.assert_called_once()

    @patch('backend.agents.orchestration.mark_tasks_p27_multi6.OrchestrationHub')
    def test_create_and_register_hub(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        hub = create_and_register_hub("dummy_id")
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("dummy_id")
        self.assertEqual(hub, mock_hub)

    def test_update_hub_heartbeat(self):
        mock_hub = MagicMock()
        update_hub_heartbeat(mock_hub)
        mock_hub.flash_update_heartbeat.assert_called_once()

    def test_mark_task_failure(self):
        mock_hub = MagicMock()
        mark_task_failure(mock_hub, "task_123", {"err": "some_error"})
        mock_hub.mark_task_done.assert_called_once_with("task_123", "fail", {"err": "some_error"})

    def test_log_task_failure_completion(self):
        with patch('builtins.print') as mock_print:
            log_task_failure_completion()
        mock_print.assert_called_once_with("TASK_MARKED_FAIL")

    def test_process_task_failure_pipeline(self):
        mock_hub = MagicMock()
        with patch('builtins.print') as mock_print:
            process_task_failure_pipeline(mock_hub, "task_123", {"err": "some_error"})
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with("task_123", "fail", {"err": "some_error"})
        mock_print.assert_called_once_with("TASK_MARKED_FAIL")

    def test_display_latest_status(self):
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "status_text"}
        with patch('builtins.print') as mock_print:
            display_latest_status(mock_hub)
        
        mock_hub.generate_flash_status.assert_called_once()
        mock_print.assert_any_call("=== STATUS ===")
        mock_print.assert_any_call("status_text")
        mock_print.assert_any_call("==============")

if __name__ == '__main__':
    unittest.main()
