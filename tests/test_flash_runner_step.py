import unittest
import sys
from unittest.mock import MagicMock, patch
from io import StringIO
from backend.agents.orchestration.flash_runner_step import main

class TestFlashRunnerStep(unittest.TestCase):
    @patch("backend.agents.orchestration.flash_runner_step.OrchestrationHub")
    def test_main_success(self, mock_hub_class):
        # Arrange
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "Mock Status"}
        
        # Act
        main()
        
        # Assert
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            "T-batch_394f90-refactor-000",
            "fail",
            {
                "subagent_id": "4a2560b1-426b-4dbd-b5e5-9659a37d87c9",
                "error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model.",
                "message": "Subagent failed to start due to Gemini API rate limits (429 RESOURCE_EXHAUSTED)."
            }
        )
        mock_hub.generate_flash_status.assert_called_once()

    @patch("backend.agents.orchestration.flash_runner_step.OrchestrationHub")
    def test_main_exception_handling(self, mock_hub_class):
        # Arrange
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.flash_update_heartbeat.side_effect = Exception("Heartbeat update failed")
        
        # Capture stderr to verify error output
        stderr_capture = StringIO()
        
        # Act & Assert
        # 例外が発生したときに sys.exit(1) が呼ばれることを確認する
        with patch("sys.stderr", stderr_capture):
            with self.assertRaises(SystemExit) as cm:
                main()
        
        # SystemExit が 1 で終了したことを確認
        self.assertEqual(cm.exception.code, 1)
        # エラーメッセージが標準エラー出力に出力されていることを確認
        self.assertIn("Error in flash_runner_step: Heartbeat update failed", stderr_capture.getvalue())
