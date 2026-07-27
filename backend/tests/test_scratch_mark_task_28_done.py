import sys
import os
import runpy
from unittest.mock import patch, MagicMock

def test_scratch_mark_task_28_done():
    # OrchestrationHub をモック化する
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # sys.path を退避
        original_path = list(sys.path)
        
        # setup_project_path() の if ブロックをカバーするため、
        # sys.path からプロジェクトルートを一時的に削除する
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        while project_root in sys.path:
            sys.path.remove(project_root)
        
        # すでにインポートされている可能性に備えてキャッシュを削除
        sys.modules.pop('backend.scratch.mark_task_28_done', None)
        
        try:
            # モジュールを import して関数を呼び出す
            from backend.scratch.mark_task_28_done import mark_task_28_completed
            mark_task_28_completed()
        finally:
            # sys.path を元に戻す
            sys.path = original_path
            
        # 呼び出しの検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            task_id="T-batch_769699-thumbnail-028",
            result="pass",
            report={
                "message": "routers/segments.py: カバレッジ 100% 達成。export_subtitles エンドポイントの422エラーバグを修正し、テストを実装",
                "changed_files": ["backend/routers/segments.py", "backend/tests/test_routers_segments.py"]
            }
        )

def test_scratch_mark_task_28_done_main_execution():
    # __name__ == "__main__" のルート（直接実行）をカバーするため runpy を使用
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # キャッシュ削除
        sys.modules.pop('backend.scratch.mark_task_28_done', None)
        
        # 直接実行のシミュレーション
        runpy.run_module("backend.scratch.mark_task_28_done", run_name="__main__")
        
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once()
