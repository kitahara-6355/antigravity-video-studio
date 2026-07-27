import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# プロジェクトルートディレクトリを sys.path に追加
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
backend_dir = Path(__file__).resolve().parents[1]

class TestMarkTasksP27Multi13(unittest.TestCase):
    def setUp(self):
        """テスト間でモジュールのキャッシュをリセットし、パッチが正しく適用されるようにする。"""
        import sys
        for key in list(sys.modules.keys()):
            if "mark_tasks_p27_multi13" in key:
                sys.modules.pop(key, None)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        
        # main を呼ぶために、テスト実行時にインポートする
        from backend.agents.orchestration.mark_tasks_p27_multi13 import main
        
        with patch('builtins.print') as mock_print:
            main()
            
            mock_hub_class.assert_called_once()
            mock_hub.register_flash_conversation_id.assert_called_once_with("0f2f32d3-7361-4ed8-b98a-ec10eb70314e")
            mock_hub.flash_update_heartbeat.assert_called_once()
            
            self.assertEqual(mock_hub.mark_task_done.call_count, 1)
            mock_hub.mark_task_done.assert_any_call(
                "T-batch_3f4c3a-refactor-000",
                "pass",
                {
                    "subagent_id": "5d22fb19-c02e-4949-9ec7-62d2a9727351",
                    "message": "transcribe_sync.py のリファクタリングタスク完了。デッドコードの除去、および非同期実行/JSON保存関数の分割。カバレッジ100%維持。",
                    "changed_files": ["backend/transcribe_sync.py"]
                }
            )
            
            mock_hub.generate_flash_status.assert_called_once()
            mock_print.assert_any_call("Marked T-batch_3f4c3a-refactor-000 as pass.")
            mock_print.assert_any_call("=== STATUS ===")
            mock_print.assert_any_call("mocked_status")
            mock_print.assert_any_call("==============")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"formatted": "mocked_status"}
        mock_hub_class.return_value = mock_hub
        
        script_path = str(backend_dir / 'agents' / 'orchestration' / 'mark_tasks_p27_multi13.py')

        with patch('builtins.print'):
            runpy.run_path(script_path, run_name='__main__')
            
        mock_hub_class.assert_called_once()

    def test_import_path_resolution_with_different_cwds(self):
        """実行時のカレントディレクトリ(CWD)が異なっていても、
        インポートパスが正しく解決されて ModuleNotFoundError が発生しないことを検証。
        """
        import subprocess
        import sys
        from pathlib import Path
        
        test_dir = Path(__file__).resolve().parent
        backend_dir = test_dir.parent
        project_root = backend_dir.parent
        
        py_code = f"""
import sys
from pathlib import Path
project_root = Path(r'{str(project_root)}')
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

target_file = Path(r'{str(backend_dir)}/agents/orchestration/mark_tasks_p27_multi13.py')
import runpy
from unittest.mock import patch, MagicMock
with patch('backend.agents.orchestration.OrchestrationHub') as mock_hub_cls:
    mock_hub = MagicMock()
    mock_hub_cls.return_value = mock_hub
    mock_hub.generate_flash_status.return_value = {{'formatted': 'ok'}}
    runpy.run_path(str(target_file), run_name='__main__')
    print('IMPORT_SUCCESS')
"""
        
        res = subprocess.run(
            [sys.executable, "-"],
            cwd=str(backend_dir),
            input=py_code,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        self.assertEqual(res.returncode, 0, f"Execution failed in backend CWD: {res.stderr}")
        self.assertIn("IMPORT_SUCCESS", res.stdout)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_initialize_hub_explicitly(self, mock_hub_class):
        """initialize_hub 関数が OrchestrationHub を正しく初期化し、
        会話IDを登録した上で心拍を更新することを検証する新規テスト。
        """
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        from backend.agents.orchestration.mark_tasks_p27_multi13 import initialize_hub
        
        test_conv_id = "dummy-conv-id-for-testing-12345"
        result_hub = initialize_hub(test_conv_id)
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with(test_conv_id)
        mock_hub.flash_update_heartbeat.assert_called_once()
        self.assertEqual(result_hub, mock_hub)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_handles_initialize_hub_error(self, mock_hub_class):
        """OrchestrationHub初期化時のOSError例外がキャッチされ、
        sys.exit(1)で終了することを検証。
        """
        mock_hub_class.side_effect = OSError("Disk full")
        
        from backend.agents.orchestration.mark_tasks_p27_multi13 import main
        
        with patch('sys.stderr') as mock_stderr, self.assertRaises(SystemExit) as cm:
            main()
            
        self.assertEqual(cm.exception.code, 1)
        any_stderr_contains_msg = any(
            "Disk full" in str(arg) for call in mock_stderr.write.call_args_list for arg in call[0]
        )
        self.assertTrue(any_stderr_contains_msg, "Error message should contain exception message")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_handles_mark_task_error(self, mock_hub_class):
        """mark_task_done実行時のValueError例外がキャッチされ、
        sys.exit(1)で終了することを検証。
        """
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.mark_task_done.side_effect = ValueError("Task not found")
        
        from backend.agents.orchestration.mark_tasks_p27_multi13 import main
        
        with patch('sys.stderr') as mock_stderr, self.assertRaises(SystemExit) as cm:
            main()
            
        self.assertEqual(cm.exception.code, 1)
        any_stderr_contains_msg = any(
            "Task not found" in str(arg) for call in mock_stderr.write.call_args_list for arg in call[0]
        )
        self.assertTrue(any_stderr_contains_msg, "Error message should contain exception message")

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_handles_print_status_error(self, mock_hub_class):
        """generate_flash_status実行時のKeyError例外がキャッチされ、
        sys.exit(1)で終了することを検証。
        """
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.side_effect = KeyError("formatted key missing")
        
        from backend.agents.orchestration.mark_tasks_p27_multi13 import main
        
        with patch('sys.stderr') as mock_stderr, self.assertRaises(SystemExit) as cm:
            main()
            
        self.assertEqual(cm.exception.code, 1)
        any_stderr_contains_key = any(
            "formatted key missing" in str(arg) for call in mock_stderr.write.call_args_list for arg in call[0]
        )
        self.assertTrue(any_stderr_contains_key, "Error message should contain key name")

if __name__ == '__main__':
    unittest.main()
