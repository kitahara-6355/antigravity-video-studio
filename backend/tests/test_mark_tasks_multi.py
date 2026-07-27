import unittest
from unittest.mock import MagicMock, patch
import argparse
from agents.orchestration.mark_tasks_multi import (
    parse_args,
    initialize_hub,
    mark_single_task,
    mark_multiple_tasks,
    print_status,
    main,
    DEFAULT_CONVERSATION_ID,
    DEFAULT_TASKS
)

class TestMarkTasksMulti(unittest.TestCase):
    @patch('argparse.ArgumentParser.parse_args')
    def test_parse_args_defaults(self, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
            conversation_id=DEFAULT_CONVERSATION_ID,
            task_id=None,
            status="pass",
            message=None,
            changed_files=None
        )
        args = parse_args()
        self.assertEqual(args.conversation_id, DEFAULT_CONVERSATION_ID)
        self.assertIsNone(args.task_id)

    @patch('agents.orchestration.mark_tasks_multi.OrchestrationHub')
    def test_initialize_hub(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        hub = initialize_hub("dummy-conv-id")
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("dummy-conv-id")
        mock_hub.flash_update_heartbeat.assert_called_once()
        self.assertEqual(hub, mock_hub)

    def test_mark_single_task(self):
        mock_hub = MagicMock()
        result = {"message": "done", "changed_files": []}
        
        mark_single_task(mock_hub, "task-1", "pass", result)
        
        mock_hub.mark_task_done.assert_called_once_with("task-1", "pass", result)

    def test_mark_multiple_tasks(self):
        mock_hub = MagicMock()
        tasks = [
            {"task_id": "t1", "status": "pass", "result": {"message": "m1"}},
            {"task_id": "t2", "status": "fail", "result": {"message": "m2"}}
        ]
        
        mark_multiple_tasks(mock_hub, tasks)
        
        self.assertEqual(mock_hub.mark_task_done.call_count, 2)
        mock_hub.mark_task_done.assert_any_call("t1", "pass", {"message": "m1"})
        mock_hub.mark_task_done.assert_any_call("t2", "fail", {"message": "m2"})

    @patch('agents.orchestration.mark_tasks_multi.OrchestrationHub')
    def test_print_status(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        with patch('builtins.print') as mock_print:
            print_status(mock_hub)
            mock_print.assert_called_once_with('FLASH_STATUS:{"status": "ok"}')

    @patch('agents.orchestration.mark_tasks_multi.check_task_exists')
    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    @patch('agents.orchestration.mark_tasks_multi.mark_single_task')
    @patch('agents.orchestration.mark_tasks_multi.mark_multiple_tasks')
    @patch('agents.orchestration.mark_tasks_multi.print_status')
    def test_main_with_task_id(self, mock_print_status, mock_mark_multi, mock_mark_single, mock_init_hub, mock_parse_args, mock_check_exists):
        mock_check_exists.return_value = True
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="pass",
            message="msg",
            changed_files=["f1.py"]
        )
        mock_parse_args.return_value = mock_args
        mock_hub = MagicMock()
        mock_init_hub.return_value = mock_hub
        
        main()
        
        mock_parse_args.assert_called_once()
        mock_init_hub.assert_called_once_with("conv-123")
        mock_mark_single.assert_called_once_with(mock_hub, "task-123", "pass", {
            "message": "msg",
            "changed_files": ["f1.py"]
        })
        mock_mark_multi.assert_not_called()
        mock_print_status.assert_called_once_with(mock_hub)

    @patch('agents.orchestration.mark_tasks_multi.check_task_exists')
    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    @patch('agents.orchestration.mark_tasks_multi.mark_single_task')
    @patch('agents.orchestration.mark_tasks_multi.mark_multiple_tasks')
    @patch('agents.orchestration.mark_tasks_multi.print_status')
    def test_main_without_task_id(self, mock_print_status, mock_mark_multi, mock_mark_single, mock_init_hub, mock_parse_args, mock_check_exists):
        mock_check_exists.return_value = True
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id=None,
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_hub = MagicMock()
        mock_init_hub.return_value = mock_hub
        
        main()
        
        mock_parse_args.assert_called_once()
        mock_init_hub.assert_called_once_with("conv-123")
        mock_mark_single.assert_not_called()
        mock_mark_multi.assert_called_once_with(mock_hub, DEFAULT_TASKS)
        mock_print_status.assert_called_once_with(mock_hub)

    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    def test_main_invalid_status(self, mock_parse_args):
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="invalid-status",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch('agents.orchestration.mark_tasks_multi.check_task_exists')
    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    def test_main_non_existent_task_id(self, mock_init_hub, mock_parse_args, mock_check_exists):
        mock_check_exists.return_value = False
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="non-existent-task-id",
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_hub = MagicMock()
        mock_init_hub.return_value = mock_hub
        
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    def test_main_with_exception(self, mock_init_hub, mock_parse_args):
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_init_hub.side_effect = OSError("Hub initialisation failed")
        
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch('agents.orchestration.mark_tasks_multi.safe_read_json')
    def test_check_task_exists_file_not_found(self, mock_safe_read):
        mock_safe_read.return_value = None
        from agents.orchestration.mark_tasks_multi import check_task_exists
        self.assertFalse(check_task_exists("task-123"))

    @patch('agents.orchestration.mark_tasks_multi.safe_read_json')
    def test_check_task_exists_valid_data(self, mock_safe_read):
        mock_safe_read.return_value = {
            "tasks": [{"id": "task-123"}, {"id": "task-456"}]
        }
        from agents.orchestration.mark_tasks_multi import check_task_exists
        self.assertTrue(check_task_exists("task-123"))
        self.assertFalse(check_task_exists("task-789"))

    @patch('agents.orchestration.mark_tasks_multi.safe_read_json')
    def test_check_task_exists_invalid_json(self, mock_safe_read):
        mock_safe_read.return_value = None
        from agents.orchestration.mark_tasks_multi import check_task_exists
        self.assertFalse(check_task_exists("task-123"))

    @patch('agents.orchestration.mark_tasks_multi.safe_read_json')
    def test_check_task_exists_corrupted_structure(self, mock_safe_read):
        mock_safe_read.return_value = {
            "tasks": "not-a-list"
        }
        from agents.orchestration.mark_tasks_multi import check_task_exists
        self.assertFalse(check_task_exists("task-123"))

        mock_safe_read.return_value = {
            "tasks": [None, 123, "string"]
        }
        self.assertFalse(check_task_exists("task-123"))

    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    def test_main_unexpected_exception(self, mock_init_hub, mock_parse_args):
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_init_hub.side_effect = TypeError("Unexpected Type Error")
        
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    def test_main_runtime_exception(self, mock_init_hub, mock_parse_args):
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_init_hub.side_effect = RuntimeError("Unexpected Runtime Error")
        
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

    @patch('agents.orchestration.mark_tasks_multi.parse_args')
    @patch('agents.orchestration.mark_tasks_multi.initialize_hub')
    def test_main_import_exception(self, mock_init_hub, mock_parse_args):
        mock_args = argparse.Namespace(
            conversation_id="conv-123",
            task_id="task-123",
            status="pass",
            message=None,
            changed_files=None
        )
        mock_parse_args.return_value = mock_args
        mock_init_hub.side_effect = ImportError("Unexpected Import Error")
        
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)

if __name__ == '__main__':
    unittest.main()