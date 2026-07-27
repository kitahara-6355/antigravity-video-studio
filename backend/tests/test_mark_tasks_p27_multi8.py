import sys
from unittest.mock import MagicMock, patch
import runpy

def test_main():
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mock_status_formatted"}
        
        from backend.agents.orchestration.mark_tasks_p27_multi8 import main
        main()
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")
        mock_hub.flash_update_heartbeat.assert_called_once()
        
        assert mock_hub.mark_task_done.call_count == 2
        mock_hub.mark_task_done.assert_any_call(
            "T-batch_c4f4d2-test_weaver-000",
            "fail",
            {"error": "RESOURCE_EXHAUSTED (code 429): You have exhausted your capacity on this model."}
        )
        mock_hub.mark_task_done.assert_any_call(
            "T-batch_c4f4d2-test_weaver-001",
            "pass",
            {
                "message": "verify_collaborative_model.py の未カバー行テスト追加完了 (カバレッジ 81% -> 100%)",
                "changed_files": ["backend/tests/test_verify_collaborative_model.py"]
            }
        )
        mock_hub.generate_flash_status.assert_called_once()

def test_script_execution():
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mock_status_formatted"}
        
        # RuntimeWarningを回避するためにキャッシュから削除
        sys.modules.pop("backend.agents.orchestration.mark_tasks_p27_multi8", None)
        
        runpy.run_module(
            "backend.agents.orchestration.mark_tasks_p27_multi8",
            run_name="__main__",
            alter_sys=True
        )
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")

def test_script_execution_via_path():
    import os
    # スクリプトの絶対パスを算出
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.abspath(os.path.join(current_dir, "..", "agents", "orchestration", "mark_tasks_p27_multi8.py"))
    
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"formatted": "mock_status_formatted"}
        
        # モジュールキャッシュを削除
        sys.modules.pop("backend.agents.orchestration.mark_tasks_p27_multi8", None)
        
        # ファイルパス指定で直接実行をテスト
        runpy.run_path(script_path, run_name="__main__")
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("3ed8fce0-a204-47fd-a220-c27fecf03706")


def test_path_injection_when_not_in_sys_path():
    import os
    import sys
    from unittest.mock import MagicMock, patch
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    
    original_path = sys.path.copy()
    try:
        sys.path = [p for p in sys.path if os.path.abspath(p) != project_root]
        
        with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
            mock_hub = MagicMock()
            mock_hub_class.return_value = mock_hub
            mock_hub.generate_flash_status.return_value = {"formatted": "mock_status_formatted"}
            
            sys.modules.pop("backend.agents.orchestration.mark_tasks_p27_multi8", None)
            
            from backend.agents.orchestration.mark_tasks_p27_multi8 import main
            main()
            
            assert sys.path[0] == project_root
    finally:
        sys.path = original_path
