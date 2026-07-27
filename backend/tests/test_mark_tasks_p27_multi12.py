import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import json

# プロジェクトルートと backend ディレクトリを sys.path に絶対パスで追加
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / 'backend') not in sys.path:
    sys.path.insert(0, str(project_root / 'backend'))

from backend.agents.orchestration.hub_common import OpusQuotaExceededException

class TestMarkTasksP27Multi12(unittest.TestCase):
    def setUp(self):
        # sys.modules からモジュールを削除して、テスト毎にクリーンなインポートを可能にする
        if 'backend.agents.orchestration.mark_tasks_p27_multi12' in sys.modules:
            del sys.modules['backend.agents.orchestration.mark_tasks_p27_multi12']

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_default(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        
        from backend.agents.orchestration.mark_tasks_p27_multi12 import main
        
        with patch('builtins.print') as mock_print:
            main([])
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
            mock_hub.flash_update_heartbeat.assert_called_once()
            mock_hub.mark_task_done.assert_called_once_with(
                "T-batch_3f4c3a-thumbnail-000",
                "pass",
                {
                    "subagent_id": "c5ce3e81-796e-4f96-8454-2caa88a86c62",
                    "message": "comprehensive_preview.py サムネイル品質向上 & クロップ中央切抜き追加 & 自動検証テスト追加",
                    "changed_files": [
                        "backend/comprehensive_preview.py",
                        "backend/tests/test_comprehensive_preview.py"
                    ]
                }
            )
            mock_hub.generate_flash_status.assert_called_once()
            mock_print.assert_any_call("Marked T-batch_3f4c3a-thumbnail-000 as pass.")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_custom_args(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        
        from backend.agents.orchestration.mark_tasks_p27_multi12 import main
        
        custom_details = {"test_key": "test_val"}
        args = [
            "--conversation-id", "custom-conv-id",
            "--task-id", "custom-task-id",
            "--status", "fail",
            "--details", json.dumps(custom_details)
        ]
        
        with patch('builtins.print') as mock_print:
            main(args)
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("custom-conv-id")
            mock_hub.flash_update_heartbeat.assert_called_once()
            mock_hub.mark_task_done.assert_called_once_with(
                "custom-task-id",
                "fail",
                custom_details
            )
            mock_print.assert_any_call("Marked custom-task-id as fail.")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_invalid_details_json(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        from backend.agents.orchestration.mark_tasks_p27_multi12 import main
        
        args = ["--details", "{invalid json}"]
        with patch('sys.exit') as mock_exit, patch('builtins.print') as mock_print:
            main(args)
            mock_exit.assert_called_once_with(1)
            mock_hub.flash_report_error.assert_called_once()
            args_call = mock_hub.flash_report_error.call_args[0][0]
            self.assertIn("JSONDecodeError", args_call)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_invalid_details_not_dict(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        from backend.agents.orchestration.mark_tasks_p27_multi12 import main
        
        args = ["--details", "[1, 2, 3]"]
        with patch('sys.exit') as mock_exit, patch('builtins.print') as mock_print:
            main(args)
            mock_exit.assert_called_once_with(1)
            mock_hub.flash_report_error.assert_called_once()
            args_call = mock_hub.flash_report_error.call_args[0][0]
            self.assertIn("ValueError", args_call)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_various_exceptions(self, mock_hub_class):
        exceptions_to_test = [
            (FileNotFoundError("file not found"), "FileNotFoundError"),
            (OSError("os error"), "OSError"),
            (ImportError("import error"), "ImportError"),
            (ValueError("value error"), "ValueError"),
            (TypeError("type error"), "TypeError"),
            (KeyError("key error"), "KeyError"),
            (OpusQuotaExceededException("quota exceeded"), "OpusQuotaExceededException"),
            (Exception("unexpected error"), "UnexpectedError"),
        ]

        for exc, expected_name in exceptions_to_test:
            mock_hub = MagicMock()
            mock_hub_class.return_value = mock_hub
            mock_hub.flash_update_heartbeat.side_effect = exc
            
            if 'backend.agents.orchestration.mark_tasks_p27_multi12' in sys.modules:
                del sys.modules['backend.agents.orchestration.mark_tasks_p27_multi12']
            
            from backend.agents.orchestration.mark_tasks_p27_multi12 import main
            
            with patch('sys.exit') as mock_exit, patch('builtins.print') as mock_print:
                main([])
                mock_exit.assert_called_once_with(1)
                mock_hub.flash_report_error.assert_called_once()
                args_call = mock_hub.flash_report_error.call_args[0][0]
                self.assertIn(expected_name, args_call)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_handle_exception_report_failure(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.flash_update_heartbeat.side_effect = ValueError("value error")
        mock_hub.flash_report_error.side_effect = Exception("failed to report")
        
        from backend.agents.orchestration.mark_tasks_p27_multi12 import main
        
        with patch('sys.exit') as mock_exit, patch('builtins.print') as mock_print:
            main([])
            mock_exit.assert_called_once_with(1)
            # mock_print のいずれかの呼び出しで "Failed to report error to hub" が出力されたことを確認
            printed_msgs = [call[0][0] for call in mock_print.call_args_list if len(call[0]) > 0 and isinstance(call[0][0], str)]
            self.assertTrue(any("Failed to report error to hub" in msg for msg in printed_msgs))

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        mock_hub_class.return_value = mock_hub
        
        script_path = str(project_root / 'backend' / 'agents' / 'orchestration' / 'mark_tasks_p27_multi12.py')
        with patch('builtins.print'):
            runpy.run_path(script_path, run_name='__main__')
            
        mock_hub_class.assert_called_once()

if __name__ == '__main__':
    unittest.main()
