import os
import json
import pytest
import subprocess
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend import run_self_improvement_loop

# --- run_pipeline のテスト ---

@patch("backend.run_self_improvement_loop.subprocess.run")
@patch("backend.run_self_improvement_loop.Path.exists")
@patch("backend.run_self_improvement_loop.Path.mkdir")
@patch("shutil.copy")
def test_run_pipeline_success_with_copy(mock_copy, mock_mkdir, mock_exists, mock_run):
    # Setup
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 0
    mock_run.return_value = mock_proc
    mock_exists.return_value = True

    # Run
    result = run_self_improvement_loop.run_pipeline()

    # Assertions
    assert result is True
    mock_run.assert_called_once()
    mock_exists.assert_called_once()
    mock_mkdir.assert_called_once()
    mock_copy.assert_called_once()

@patch("backend.run_self_improvement_loop.subprocess.run")
@patch("backend.run_self_improvement_loop.Path.exists")
@patch("shutil.copy")
def test_run_pipeline_success_no_copy(mock_copy, mock_exists, mock_run):
    # Setup
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 0
    mock_run.return_value = mock_proc
    mock_exists.return_value = False

    # Run
    result = run_self_improvement_loop.run_pipeline()

    # Assertions
    assert result is True
    mock_run.assert_called_once()
    mock_exists.assert_called_once()
    mock_copy.assert_not_called()

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_run_pipeline_failure_returncode(mock_run):
    # Setup
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 1
    mock_run.return_value = mock_proc

    # Run
    result = run_self_improvement_loop.run_pipeline()

    # Assertions
    assert result is False
    mock_run.assert_called_once()

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_run_pipeline_exception(mock_run):
    # Setup
    mock_run.side_effect = subprocess.SubprocessError("Subprocess failed")

    # Run
    result = run_self_improvement_loop.run_pipeline()

    # Assertions
    assert result is False
    mock_run.assert_called_once()


# --- run_frame_extraction のテスト ---

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_run_frame_extraction_success(mock_run):
    # Setup
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 0
    mock_run.return_value = mock_proc

    # Run
    result = run_self_improvement_loop.run_frame_extraction()

    # Assertions
    assert result is True
    mock_run.assert_called_once()

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_run_frame_extraction_failure(mock_run):
    # Setup
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 1
    mock_run.return_value = mock_proc

    # Run
    result = run_self_improvement_loop.run_frame_extraction()

    # Assertions
    assert result is False
    mock_run.assert_called_once()

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_run_frame_extraction_exception(mock_run):
    # Setup
    mock_run.side_effect = OSError("OS error")

    # Run
    result = run_self_improvement_loop.run_frame_extraction()

    # Assertions
    assert result is False
    mock_run.assert_called_once()


# --- pipeline_callback のテスト ---

@patch("backend.run_self_improvement_loop.run_pipeline")
@patch("backend.run_self_improvement_loop.run_frame_extraction")
def test_pipeline_callback_success(mock_extract, mock_pipeline):
    mock_pipeline.return_value = True
    mock_extract.return_value = True

    assert run_self_improvement_loop.pipeline_callback() is True
    mock_pipeline.assert_called_once()
    mock_extract.assert_called_once()

@patch("backend.run_self_improvement_loop.run_pipeline")
@patch("backend.run_self_improvement_loop.run_frame_extraction")
def test_pipeline_callback_pipeline_fail(mock_extract, mock_pipeline):
    mock_pipeline.return_value = False

    assert run_self_improvement_loop.pipeline_callback() is False
    mock_pipeline.assert_called_once()
    mock_extract.assert_not_called()

@patch("backend.run_self_improvement_loop.run_pipeline")
@patch("backend.run_self_improvement_loop.run_frame_extraction")
def test_pipeline_callback_extract_fail(mock_extract, mock_pipeline):
    mock_pipeline.return_value = True
    mock_extract.return_value = False

    assert run_self_improvement_loop.pipeline_callback() is False
    mock_pipeline.assert_called_once()
    mock_extract.assert_called_once()


# --- git_save_results のテスト ---

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_git_save_results_success(mock_run):
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 0
    mock_run.return_value = mock_proc

    run_self_improvement_loop.git_save_results(3, True)
    assert mock_run.call_count == 2
    
    # 最初の呼び出しは git add
    first_args = mock_run.call_args_list[0][0][0]
    assert first_args[0:2] == ["git", "add"]
    
    # 2番目の呼び出しは git commit
    second_args = mock_run.call_args_list[1][0][0]
    assert second_args[0:3] == ["git", "commit", "-m"]
    assert "iteration 3" in second_args[3]
    assert "PASS" in second_args[3]

@patch("backend.run_self_improvement_loop.subprocess.run")
def test_git_save_results_failure(mock_run):
    mock_run.side_effect = subprocess.SubprocessError("Git error")
    
    # 例外がスローされず、エラーログが出力されて正常に終了することを確認
    run_self_improvement_loop.git_save_results(3, False)
    mock_run.assert_called_once()


# --- main のテスト ---

@pytest.fixture
def mock_engine_class():
    with patch("backend.run_self_improvement_loop.SelfImprovementEngine") as mock_cls:
        yield mock_cls

def test_main_success_with_history(mock_engine_class, tmp_path):
    # Setup mock engine
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    mock_engine_class.return_value = mock_engine

    # Setup temporary GRADED_PREVIEWS_DIR and history file
    temp_graded_previews = tmp_path / "graded_previews"
    temp_graded_previews.mkdir()
    history_file = temp_graded_previews / "weakness_analysis_history.json"
    dummy_history = [{"iteration": 1}, {"iteration": 2}]
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(dummy_history, f)

    # Patch variables and functions in the module
    with patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", temp_graded_previews), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
         
        run_self_improvement_loop.main()

        # Assertions
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(2, True)

def test_main_failure_no_history(mock_engine_class, tmp_path):
    # Setup mock engine
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = False
    mock_engine_class.return_value = mock_engine

    # Setup temporary GRADED_PREVIEWS_DIR (history file does not exist)
    temp_graded_previews = tmp_path / "graded_previews"
    temp_graded_previews.mkdir()

    # Patch variables and functions in the module
    with patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", temp_graded_previews), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
         
        run_self_improvement_loop.main()

        # Assertions
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, False)

def test_main_history_parse_error(mock_engine_class, tmp_path):
    # Setup mock engine
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    mock_engine_class.return_value = mock_engine

    # Setup temporary GRADED_PREVIEWS_DIR with invalid json
    temp_graded_previews = tmp_path / "graded_previews"
    temp_graded_previews.mkdir()
    history_file = temp_graded_previews / "weakness_analysis_history.json"
    with open(history_file, "w", encoding="utf-8") as f:
        f.write("invalid json")

    # Patch variables and functions in the module
    with patch("backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR", temp_graded_previews), \
         patch("backend.run_self_improvement_loop.git_save_results") as mock_git_save:
         
        run_self_improvement_loop.main()

        # Assertions
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, True)


# --- CLI 実行のテスト ---

import runpy

@patch("subprocess.run")
@patch("backend.self_improvement_engine.SelfImprovementEngine")
def test_cli_execution(mock_engine_class, mock_sub_run):
    # Setup mock engine
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    mock_engine_class.return_value = mock_engine

    # Setup mock subprocess
    mock_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_proc.returncode = 0
    mock_sub_run.return_value = mock_proc

    # Run module as __main__
    runpy.run_module("backend.run_self_improvement_loop", run_name="__main__")

    # Assertions
    mock_engine.run_loop.assert_called_once()
    mock_sub_run.assert_called()


# --- 追加のエッジケース・頑健性検証テスト ---

@patch('backend.run_self_improvement_loop.subprocess.run')
def test_run_pipeline_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=['python', 'backend/auto_full_build.py'], timeout=1200)
    result = run_self_improvement_loop.run_pipeline()
    assert result is False
    mock_run.assert_called_once()


@patch('backend.run_self_improvement_loop.subprocess.run')
def test_run_frame_extraction_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=['python', 'backend/generate_full_inspection.py'], timeout=300)
    result = run_self_improvement_loop.run_frame_extraction()
    assert result is False
    mock_run.assert_called_once()


@patch('backend.run_self_improvement_loop.subprocess.run')
def test_git_save_results_commit_failure(mock_run):
    mock_add_proc = MagicMock(spec=subprocess.CompletedProcess)
    mock_add_proc.returncode = 0
    mock_run.side_effect = [mock_add_proc, subprocess.SubprocessError('Git commit failed')]
    run_self_improvement_loop.git_save_results(3, True)
    assert mock_run.call_count == 2


@patch('backend.run_self_improvement_loop.subprocess.run')
def test_git_save_results_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=['git', 'add'], timeout=30)
    run_self_improvement_loop.git_save_results(3, True)
    mock_run.assert_called_once()


def test_main_history_invalid_type(mock_engine_class, tmp_path):
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    mock_engine_class.return_value = mock_engine
    temp_graded_previews = tmp_path / 'graded_previews'
    temp_graded_previews.mkdir()
    history_file = temp_graded_previews / 'weakness_analysis_history.json'
    with open(history_file, 'w', encoding='utf-8') as f:
        f.write('12345')
    with patch('backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR', temp_graded_previews), \
         patch('backend.run_self_improvement_loop.git_save_results') as mock_git_save:
        run_self_improvement_loop.main()
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, True)


def test_main_history_empty_file(mock_engine_class, tmp_path):
    mock_engine = MagicMock()
    mock_engine.run_loop.return_value = True
    mock_engine_class.return_value = mock_engine
    temp_graded_previews = tmp_path / 'graded_previews'
    temp_graded_previews.mkdir()
    history_file = temp_graded_previews / 'weakness_analysis_history.json'
    with open(history_file, 'w', encoding='utf-8') as f:
        f.write('')
    with patch('backend.run_self_improvement_loop.GRADED_PREVIEWS_DIR', temp_graded_previews), \
         patch('backend.run_self_improvement_loop.git_save_results') as mock_git_save:
        run_self_improvement_loop.main()
        mock_engine.run_loop.assert_called_once()
        mock_git_save.assert_called_once_with(0, True)
