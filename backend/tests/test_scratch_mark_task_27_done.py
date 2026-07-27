import sys
import os
from unittest.mock import patch, MagicMock

def test_scratch_mark_task_27_done():
    # OrchestrationHub をモック化する
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        # すでにインポートされている可能性に備えてキャッシュを削除
        sys.modules.pop('backend.scratch.mark_task_27_done', None)
        
        # 普通にモジュールを import する
        import backend.scratch.mark_task_27_done
        
        # インポートしただけでは main() は動かず、副作用がないことを検証
        mock_hub.flash_update_heartbeat.assert_not_called()
        mock_hub.mark_task_done.assert_not_called()
        
        # main を手動で実行して、正しく動作することを検証
        exit_code = backend.scratch.mark_task_27_done.main()
        assert exit_code == 0
            
        # 呼び出しの検証
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once_with(
            task_id="T-batch_769699-thumbnail-027",
            result="pass",
            report={
                "message": "generation_engine.py: カバレッジ 100% 達成。例外ハンドリングやフォールバック動作のテストを追加",
                "changed_files": ["backend/tests/test_shared/test_batch12_gen_legacy_branding.py"]
            }
        )

def test_scratch_mark_task_27_done_import_error():
    # sys.modules に None を設定して ImportError を発生させる
    sys.modules.pop('backend.scratch.mark_task_27_done', None)
    # 既存のキャッシュをクリア
    sys.modules.pop('backend.agents.orchestration', None)
    
    # Noneを設定することでインポート時にImportErrorになる
    sys.modules['backend.agents.orchestration'] = None
    
    try:
        import backend.scratch.mark_task_27_done
        exit_code = backend.scratch.mark_task_27_done.main()
        assert exit_code == 1
    finally:
        # キャッシュを元に戻す
        sys.modules.pop('backend.agents.orchestration', None)

def test_scratch_mark_task_27_done_general_error():
    # 一般エラーが発生した場合の挙動をテスト
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        mock_hub.flash_update_heartbeat.side_effect = OSError("Mocked OS error")
        
        sys.modules.pop('backend.scratch.mark_task_27_done', None)
        import backend.scratch.mark_task_27_done
        
        exit_code = backend.scratch.mark_task_27_done.main()
        assert exit_code == 1
