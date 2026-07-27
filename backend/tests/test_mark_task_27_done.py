import pytest
import sys
import os
import runpy
from unittest.mock import patch, MagicMock
import backend.scratch.mark_task_27_done as target

def test_main_success():
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance) as mock_hub_class:
        res = target.main()
        assert res == 0
        mock_hub_class.assert_called_once()
        mock_hub_instance.flash_update_heartbeat.assert_called_once()
        mock_hub_instance.mark_task_done.assert_called_once_with(
            task_id="T-batch_769699-thumbnail-027",
            result="pass",
            report={
                "message": "generation_engine.py: \u30ab\u30d0\u30ec\u30c3\u30b8 100% \u9054\u6210\u3002\u4f8b\u5916\u30cf\u30f3\u30c9\u30ea\u30f3\u30b0\u3084\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af\u52d5\u4f5c\u306e\u30c6\u30b9\u30c8\u3092\u8ffd\u52a0",
                "changed_files": ["backend/tests/test_shared/test_batch12_gen_legacy_branding.py"]
            }
        )

def test_main_import_error():
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if "backend.agents.orchestration" in name or name == "backend.agents.orchestration":
            raise ImportError("Mocked import error")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        with patch.dict(sys.modules):
            if "backend.agents.orchestration" in sys.modules:
                del sys.modules["backend.agents.orchestration"]
            with patch("sys.stderr.write") as mock_stderr_write:
                res = target.main()
                assert res == 1
                mock_stderr_write.assert_called()

@pytest.mark.parametrize("exception_class", [OSError, ValueError, KeyError])
def test_main_exception_handling(exception_class):
    mock_hub_instance = MagicMock()
    mock_hub_instance.flash_update_heartbeat.side_effect = exception_class("??????")
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
        with patch("sys.stderr.write") as mock_stderr_write:
            res = target.main()
            assert res == 1
            mock_stderr_write.assert_called()

def test_script_run_main_via_runpy():
    mock_hub_instance = MagicMock()
    with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance) as mock_hub_class:
        with patch("sys.exit") as mock_exit:
            root = r"C:\Users\PC_User\.gemini\antigravity\brain\50f52326-96dd-4dec-8934-86d0eaf8e744\.system_generated\worktrees\subagent-test-weaver-Agent-self-aa5a07bd"
            original_path = sys.path.copy()
            if root in sys.path:
                sys.path.remove(root)
            
            try:
                script_path = os.path.join(root, "backend", "scratch", "mark_task_27_done.py")
                runpy.run_path(script_path, run_name="__main__")
                mock_exit.assert_called_once_with(0)
            finally:
                sys.path = original_path

def test_script_run_main_via_runpy_import_error():
    original_import = __import__
    def mock_import(name, *args, **kwargs):
        if "backend.agents.orchestration" in name or name == "backend.agents.orchestration":
            raise ImportError("Mocked import error")
        return original_import(name, *args, **kwargs)
        
    with patch("builtins.__import__", side_effect=mock_import):
        with patch("sys.exit") as mock_exit:
            with patch("sys.stderr.write") as mock_stderr:
                with patch.dict(sys.modules):
                    if "backend.agents.orchestration" in sys.modules:
                        del sys.modules["backend.agents.orchestration"]
                    
                    root = r"C:\Users\PC_User\.gemini\antigravity\brain\50f52326-96dd-4dec-8934-86d0eaf8e744\.system_generated\worktrees\subagent-test-weaver-Agent-self-aa5a07bd"
                    script_path = os.path.join(root, "backend", "scratch", "mark_task_27_done.py")
                    runpy.run_path(script_path, run_name="__main__")
                    mock_exit.assert_called_once_with(1)
                    mock_stderr.assert_called()
