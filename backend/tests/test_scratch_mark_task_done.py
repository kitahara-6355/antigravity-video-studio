import sys
import importlib
from unittest.mock import patch

def test_scratch_mark_task_done():
    original_path = list(sys.path)
    if 'backend.scratch.mark_task_c48ea3_003_done' in sys.modules:
        del sys.modules['backend.scratch.mark_task_c48ea3_003_done']
    try:
        with patch('backend.agents.orchestration.OrchestrationHub') as MockHub:
            mock_instance = MockHub.return_value
            import backend.scratch.mark_task_c48ea3_003_done
            mock_instance.flash_update_heartbeat.assert_called_once()
            mock_instance.mark_task_done.assert_called_once_with(
                task_id='T-batch_c48ea3-thumbnail-003',
                result='pass',
                report={
                    'message': 'core/context.py: カバレッジ 100% 維持。エッジケース・異常系のテストケースを追加して堅牢性を向上',
                    'changed_files': ['backend/tests/test_context.py']
                }
            )
    finally:
        sys.path = original_path
