"""
test_run_self_improvement_loop.py — run_self_improvement_loop.py のユニットテスト
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import subprocess
import shutil
import json
import runpy
import sys

# プロジェクトルートをパスに追加
backend_dir = Path(__file__).resolve().parents[1] / 'backend'
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.run_self_improvement_loop import (
    run_pipeline,
    run_frame_extraction,
    pipeline_callback,
    git_save_results,
    main
)

# --- run_pipeline のテスト ---

def test_run_pipeline_success(tmp_path):
    """正常系: パイプライン実行が成功し、動画が存在してコピーされる"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path), \
         patch("shutil.copy") as mock_copy:
        
        mock_run.return_value = MagicMock(returncode=0)
        
        src_file = tmp_path / "soul_narrative_full_v1.mp4"
        src_file.touch()
        
        result = run_pipeline()
        
        assert result is True
        mock_run.assert_called_once()
        mock_copy.assert_called_once()
        dest_dir = tmp_path / "vault-outputs" / "preview"
        assert dest_dir.exists()

def test_run_pipeline_no_video(tmp_path):
    """準正常系: パイプライン実行は成功するが、動画ファイルが見つからない"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path), \
         patch("shutil.copy") as mock_copy:
        
        mock_run.return_value = MagicMock(returncode=0)
        
        # 動画ファイルは作成しない
        result = run_pipeline()
        
        assert result is True
        mock_run.assert_called_once()
        mock_copy.assert_not_called()

def test_run_pipeline_failure(tmp_path):
    """異常系: パイプラインの returncode が 0 以外"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path):
        
        mock_run.return_value = MagicMock(returncode=1)
        
        result = run_pipeline()
        
        assert result is False
        mock_run.assert_called_once()

def test_run_pipeline_exception(tmp_path):
    """異常系: subprocess.run 実行時に例外が発生する"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path):
        
        mock_run.side_effect = subprocess.SubprocessError("Subprocess failed")
        
        result = run_pipeline()
        
        assert result is False
        mock_run.assert_called_once()


# --- run_frame_extraction のテスト ---

def test_run_frame_extraction_success(tmp_path):
    """正常系: フレーム画像抽出が成功する"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path):
        
        mock_run.return_value = MagicMock(returncode=0)
        
        result = run_frame_extraction()
        
        assert result is True
        mock_run.assert_called_once()

def test_run_frame_extraction_failure(tmp_path):
    """異常系: フレーム画像抽出の returncode が 0 以外"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path):
        
        mock_run.return_value = MagicMock(returncode=1)
        
        result = run_frame_extraction()
        
        assert result is False
        mock_run.assert_called_once()

def test_run_frame_extraction_exception(tmp_path):
    """異常系: フレーム画像抽出で例外が発生する"""
    with patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.BASE_DIR", tmp_path):
        
        mock_run.side_effect = OSError("OS error")
        
        result = run_frame_extraction()
        
        assert result is False
        mock_run.assert_called_once()


# --- pipeline_callback のテスト ---

def test_pipeline_callback_all_success():
    """正常系: 動画生成、フレーム抽出ともに成功"""
    with patch("backend.run_self_improvement_loop.run_pipeline") as mock_pipeline, \
         patch("backend.run_self_improvement_loop.run_frame_extraction") as mock_frame:
        
        mock_pipeline.return_value = True
        mock_frame.return_value = True
        
        result = pipeline_callback()
        
        assert result is True
        mock_pipeline.assert_called_once()
        mock_frame.assert_called_once()

def test_pipeline_callback_pipeline_fails():
    """異常系: 動画生成が失敗し、フレーム抽出はスキップされる"""
    with patch("backend.run_self_improvement_loop.run_pipeline") as mock_pipeline, \
         patch("backend.run_self_improvement_loop.run_frame_extraction") as mock_frame:
        
        mock_pipeline.return_value = False
        
        result = pipeline_callback()
        
        assert result is False
        mock_pipeline.assert_called_once()
        mock_frame.assert_not_called()

def test_pipeline_callback_frame_fails():
    """異常系: 動画生成は成功するが、フレーム抽出が失敗する"""
    with patch("backend.run_self_improvement_loop.run_pipeline") as mock_pipeline, \
         patch("backend.run_self_improvement_loop.run_frame_extraction") as mock_frame:
        
        mock_pipeline.return_value = True
        mock_frame.return_value = False
        
        result = pipeline_callback()
        
        assert result is False
        mock_pipeline.assert_called_once()
        mock_frame.assert_called_once()


# --- git_save_results のテスト ---

def test_git_save_results_success():
    """git_save_results が正常に Git add と Git commit を実行すること"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        git_save_results(3, True)
        
        assert mock_run.call_count == 2
        args1 = mock_run.call_args_list[0][0][0]
        args2 = mock_run.call_args_list[1][0][0]
        assert "git" in args1
        assert "add" in args1
        assert "git" in args2
        assert "commit" in args2
        assert any("iteration 3: PASS" in item for item in args2)

def test_git_save_results_failure():
    """git_save_results 実行中に Git コマンドがエラーになっても、適切にキャッチされてクラッシュしないこと"""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.SubprocessError("Git error")
        
        git_save_results(2, False)
        
        mock_run.assert_called_once()


# --- main のテスト ---

def test_main_success(tmp_path):
    """main 正常系: 改善成功、履歴ファイルが存在する場合"""
    history_path = tmp_path / "weakness_analysis_history.json"
    history_data = [{"iteration": 1, "score": 85}, {"iteration": 2, "score": 92}]
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history_data, f)
        
    with patch("backend.run_self_improvement_loop.SelfImprovementEngine") as mock_engine_cls, \
         patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", tmp_path), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
        
        mock_engine = MagicMock()
        mock_engine.run_loop.return_value = True
        mock_engine_cls.return_value = mock_engine
        
        main()
        
        mock_engine.run_loop.assert_called_once_with(
            pipeline_callback=pipeline_callback,
            max_iterations=5
        )
        mock_git_save.assert_called_once_with(2, True)

def test_main_failure_no_history(tmp_path):
    """main 準正常系: 改善失敗、履歴ファイルが存在しない場合"""
    with patch("backend.run_self_improvement_loop.SelfImprovementEngine") as mock_engine_cls, \
         patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", tmp_path), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
        
        mock_engine = MagicMock()
        mock_engine.run_loop.return_value = False
        mock_engine_cls.return_value = mock_engine
        
        main()
        
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, False)

def test_main_history_read_error(tmp_path):
    """main 準正常系: 履歴ファイルの読み込み時に例外が発生する場合"""
    history_path = tmp_path / "weakness_analysis_history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        f.write("{invalid json")
        
    with patch("backend.run_self_improvement_loop.SelfImprovementEngine") as mock_engine_cls, \
         patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", tmp_path), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
        
        mock_engine = MagicMock()
        mock_engine.run_loop.return_value = True
        mock_engine_cls.return_value = mock_engine
        
        main()
        
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, True)


# --- __main__ ガードのテスト ---

def test_module_main_guard(tmp_path):
    """run_self_improvement_loop.py がスクリプトとして直接実行された時の __main__ ガードの実行を検証"""
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    
    with patch("backend.self_improvement_engine.SelfImprovementEngine") as mock_engine_cls, \
         patch("subprocess.run") as mock_run, \
         patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", tmp_path):
        
        mock_engine_cls.return_value = mock_engine
        mock_run.return_value = MagicMock(returncode=0)
        
        runpy.run_module("backend.run_self_improvement_loop", run_name="__main__")
        
        mock_engine.run_loop.assert_called_once()
        assert mock_run.call_count >= 2
