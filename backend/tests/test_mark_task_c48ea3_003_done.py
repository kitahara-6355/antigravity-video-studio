import sys
import importlib
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_mark_task_c48ea3_003_done_execution():
    """backend/scratch/mark_task_c48ea3_003_done.py が正しく実行されることを検証する"""
    original_path = list(sys.path)
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    try:
        mock_hub_instance = MagicMock()
        
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            # すでにインポートされている可能性に備えて sys.modules から削除
            sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
            
            # モジュールをインポート
            module = importlib.import_module("backend.scratch.mark_task_c48ea3_003_done")
            
            # リファクタリングされた関数を呼び出し
            module.report_thumbnail_task_completion(mock_hub_instance)
            
            # 検証
            mock_hub_instance.flash_update_heartbeat.assert_called_once()
            mock_hub_instance.mark_task_done.assert_called_once_with(
                task_id="T-batch_c48ea3-thumbnail-003",
                result="pass",
                report={
                    "message": "core/context.py: カバレッジ 100% 維持。エッジケース・異常系のテストケースを追加して堅牢性を向上",
                    "changed_files": ["backend/tests/test_context.py"]
                }
            )
    finally:
        sys.path = original_path

def test_mark_task_c48ea3_003_done_main_execution():
    """backend/scratch/mark_task_c48ea3_003_done.py がメインスクリプトとして直接実行された場合の挙動を検証する"""
    original_path = list(sys.path)
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    try:
        mock_hub_instance = MagicMock()
        
        # OrchestrationHub をモック化して実環境に通知されないようにする
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance) as mock_hub_class:
            script_path = str(Path(__file__).parent.parent / "scratch" / "mark_task_c48ea3_003_done.py")
            
            # すでにインポートされている可能性に備えて sys.modules から削除
            sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
            
            # runpy を用いて __main__ として実行
            runpy.run_path(script_path, run_name="__main__")
            
            # 検証
            mock_hub_class.assert_called_once()
            mock_hub_instance.flash_update_heartbeat.assert_called_once()
            mock_hub_instance.mark_task_done.assert_called_once_with(
                task_id="T-batch_c48ea3-thumbnail-003",
                result="pass",
                report={
                    "message": "core/context.py: カバレッジ 100% 維持。エッジケース・異常系のテストケースを追加して堅牢性を向上",
                    "changed_files": ["backend/tests/test_context.py"]
                }
            )
    finally:
        sys.path = original_path

def test_add_project_root_to_sys_path():
    """add_project_root_to_sys_path 関数が sys.path にプロジェクトルートが存在しない場合に追加することを検証する"""
    original_path = list(sys.path)
    project_root = str(Path(__file__).parent.parent.parent)
    
    # すでにインポートされている可能性に備えて sys.modules から削除
    sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
    module = importlib.import_module("backend.scratch.mark_task_c48ea3_003_done")
    
    try:
        # sys.path から project_root を一時的に削除
        while project_root in sys.path:
            sys.path.remove(project_root)
            
        # 呼び出し
        module.add_project_root_to_sys_path()
        
        # 追加されていることを検証
        assert sys.path[0] == project_root
    finally:
        sys.path = original_path

def test_add_project_root_to_sys_path_already_exists():
    """add_project_root_to_sys_path 関数が sys.path にプロジェクトルートがすでに存在する場合に、重複して追加しないことを検証する"""
    original_path = list(sys.path)
    project_root = str(Path(__file__).parent.parent.parent)
    
    sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
    module = importlib.import_module("backend.scratch.mark_task_c48ea3_003_done")
    
    try:
        # sys.path に project_root を確実に入れておく
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
            
        initial_path_len = len(sys.path)
        
        # 呼び出し
        module.add_project_root_to_sys_path()
        
        # 配列長が変わっていない（重複追加されていない）ことを検証
        assert len(sys.path) == initial_path_len
    finally:
        sys.path = original_path

def test_report_thumbnail_task_completion_exception():
    """OrchestrationHub が例外を投げた場合に、例外が呼び出し元に適切に伝播することを検証する"""
    original_path = list(sys.path)
    project_root = str(Path(__file__).parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    try:
        mock_hub_instance = MagicMock()
        # flash_update_heartbeat が例外を投げるように設定
        mock_hub_instance.flash_update_heartbeat.side_effect = RuntimeError("Heartbeat update failed")
        
        sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
        module = importlib.import_module("backend.scratch.mark_task_c48ea3_003_done")
        
        import pytest
        with pytest.raises(RuntimeError, match="Heartbeat update failed"):
            module.report_thumbnail_task_completion(mock_hub_instance)
            
    finally:
        sys.path = original_path

def test_get_thumbnail_task_details():
    """get_thumbnail_task_details 関数が正しいタスクID、実行結果、レポート詳細を返すことを検証する"""
    sys.modules.pop("backend.scratch.mark_task_c48ea3_003_done", None)
    module = importlib.import_module("backend.scratch.mark_task_c48ea3_003_done")
    
    task_id, result, report = module.get_thumbnail_task_details()
    
    assert task_id == "T-batch_c48ea3-thumbnail-003"
    assert result == "pass"
    assert report == {
        "message": "core/context.py: カバレッジ 100% 維持。エッジケース・異常系のテストケースを追加して堅牢性を向上",
        "changed_files": ["backend/tests/test_context.py"]
    }

