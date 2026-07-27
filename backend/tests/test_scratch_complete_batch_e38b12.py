# -*- coding: utf-8 -*-
import sys
import os
import runpy
from unittest.mock import patch, MagicMock
import pytest
# テストターゲットファイルのパス
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

import backend.agents.orchestration
import backend.agents.memory.technical_debt

script_path = os.path.join(project_root, "backend", "scratch", "complete_batch_e38b12.py")
fallback_path = "C:/Users/PC_User/Desktop/script/video-automation"

@pytest.fixture(autouse=True)
def clean_imports():
    """テストごとに sys.modules や sys.path をクリーンにする"""
    # ターゲットモジュールのキャッシュを削除
    sys.modules.pop("backend.scratch.complete_batch_e38b12", None)
    
    # sys.path から不要なパスを一時的に除外する
    original_path = list(sys.path)
    
    # fallback_path と project_root を sys.path から除去
    # ただし、fallback_path が実際の project_root と同一の場合は、除去するとすべてインポートできなくなるため除外しない
    if fallback_path.lower().replace("\\", "/") != project_root.lower().replace("\\", "/"):
        while fallback_path in sys.path:
            sys.path.remove(fallback_path)
        while fallback_path.replace("/", "\\") in sys.path:
            sys.path.remove(fallback_path.replace("/", "\\"))

        
    yield
    sys.path = original_path
    sys.modules.pop("backend.scratch.complete_batch_e38b12", None)

def test_complete_batch_e38b12_success():
    """正常系のテスト"""
    # インポート時に本物が使われないよう、モックを backend.agents... にあてる
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class:
        mock_hub_instance = MagicMock()
        mock_hub_class.return_value = mock_hub_instance
        
        # ファイルを直接インポートして評価
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is True
        
        assert mock_hub_instance.mark_task_done.call_count == 4
        mock_hub_instance.submit_batch_report.assert_called_once_with(
            "batch_e38b12",
            {"passed": 4, "failed": 0, "total": 4}
        )

def test_complete_batch_e38b12_hub_init_error():
    """OrchestrationHub初期化エラー時のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_class.side_effect = Exception("Hub init error")
        mock_td_instance = MagicMock()
        mock_td_class.return_value = mock_td_instance
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False
        
        mock_td_instance.register_debt.assert_called_once()
        args, kwargs = mock_td_instance.register_debt.call_args
        assert kwargs["category"] == "MINOR_INFRA"
        assert kwargs["line_number"] == 22

def test_complete_batch_e38b12_hub_init_error_tdr_error():
    """OrchestrationHub初期化エラーかつTechnicalDebtStore登録エラーのテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_class.side_effect = Exception("Hub init error")
        mock_td_class.side_effect = Exception("TDR error")
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False

def test_complete_batch_e38b12_mark_task_done_error():
    """mark_task_done エラー時のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_instance = MagicMock()
        mock_hub_instance.mark_task_done.side_effect = Exception("Mark task error")
        mock_hub_class.return_value = mock_hub_instance
        
        mock_td_instance = MagicMock()
        mock_td_class.return_value = mock_td_instance
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False
        
        assert mock_hub_instance.mark_task_done.call_count == 4
        assert mock_td_instance.register_debt.call_count == 4

def test_complete_batch_e38b12_mark_task_done_tdr_error():
    """mark_task_doneエラーかつTechnicalDebtStore登録エラー時のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_instance = MagicMock()
        mock_hub_instance.mark_task_done.side_effect = Exception("Mark task error")
        mock_hub_class.return_value = mock_hub_instance
        
        mock_td_class.side_effect = Exception("TDR error")
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False

def test_complete_batch_e38b12_submit_report_error():
    """submit_batch_report エラー時のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_instance = MagicMock()
        mock_hub_instance.submit_batch_report.side_effect = Exception("Submit report error")
        mock_hub_class.return_value = mock_hub_instance
        
        mock_td_instance = MagicMock()
        mock_td_class.return_value = mock_td_instance
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False
        
        mock_td_instance.register_debt.assert_called_once()
        args, kwargs = mock_td_instance.register_debt.call_args
        assert kwargs["line_number"] == 97

def test_complete_batch_e38b12_submit_report_tdr_error():
    """submit_batch_reportエラーかつTechnicalDebtStore登録エラー時のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_td_class:
        
        mock_hub_instance = MagicMock()
        mock_hub_instance.submit_batch_report.side_effect = Exception("Submit report error")
        mock_hub_class.return_value = mock_hub_instance
        
        mock_td_class.side_effect = Exception("TDR error")
        
        import backend.scratch.complete_batch_e38b12 as m
        assert m.main() is False

def test_complete_batch_e38b12_main_execution_success():
    """__main__ 実行（正常系）のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("sys.exit") as mock_exit:
        
        mock_hub_instance = MagicMock()
        mock_hub_class.return_value = mock_hub_instance
        
        runpy.run_path(script_path, run_name="__main__")
        mock_exit.assert_called_once_with(0)

def test_complete_batch_e38b12_main_execution_failure():
    """__main__ 実行（異常系）のテスト"""
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
         patch("sys.exit") as mock_exit:
        
        mock_hub_class.side_effect = Exception("Hub init error")
        
        runpy.run_path(script_path, run_name="__main__")
        mock_exit.assert_called_once_with(1)

def test_complete_batch_e38b12_sys_path_insert():
    """sys.pathにproject_rootが存在しない場合に追加されることを確認するテスト"""
    # テスト開始前に sys.path から project_root も除去しておく
    original_path = list(sys.path)
    try:
        while project_root in sys.path:
            sys.path.remove(project_root)
        while project_root.replace("/", "\\") in sys.path:
            sys.path.remove(project_root.replace("/", "\\"))
            
        with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
             patch("sys.exit") as mock_exit:
            
            mock_hub_instance = MagicMock()
            mock_hub_class.return_value = mock_hub_instance
            
            # run_path で実行することで、ファイル先頭の sys.path.insert 処理を通す
            runpy.run_path(script_path, run_name="test_run")
            
            # project_root が sys.path の先頭に追加されていることを確認
            assert project_root in sys.path
            assert sys.path[0] == project_root
            
    finally:
        sys.path = original_path


def test_complete_batch_e38b12_sys_path_already_exists():
    """sys.pathにproject_rootが既に存在する場合、二重追加されないか、処理が正常終了することを確認するテスト"""
    original_path = list(sys.path)
    try:
        # project_root をあらかじめ sys.path に入れておく
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
            
        initial_count = sys.path.count(project_root)
        
        with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_class, \
             patch("sys.exit") as mock_exit:
            
            mock_hub_instance = MagicMock()
            mock_hub_class.return_value = mock_hub_instance
            
            # run_path で実行
            runpy.run_path(script_path, run_name="test_run")
            
            # sys.path に project_root が増えていないことを確認
            assert sys.path.count(project_root) == initial_count
            
    finally:
        sys.path = original_path

