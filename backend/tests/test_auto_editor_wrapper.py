"""
test_auto_editor_wrapper.py — Unit Tests for Auto-Editor Wrapper
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.video_pipeline.auto_editor_wrapper import AutoEditorWrapper


def test_resolve_command_default():
    """デフォルトでのコマンド解決が python -m auto_editor になることを確認"""
    wrapper = AutoEditorWrapper()
    assert wrapper._resolve_command() == ["python", "-m", "auto_editor"]


def test_resolve_command_custom():
    """カスタムバイナリパスが正しく解決されることを確認"""
    wrapper = AutoEditorWrapper(executable_path="/usr/bin/auto-editor")
    assert wrapper._resolve_command() == ["/usr/bin/auto-editor"]


@patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper._run_command")
def test_run_smart_cut_success(mock_run, tmp_path):
    """正常系の呼び出しで正しい引数が組み立てられることを確認"""
    input_file = tmp_path / "dummy_input.mp4"
    output_file = tmp_path / "dummy_output.mp4"
    input_file.write_text("dummy video content")

    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="auto-editor output summary",
        stderr=""
    )

    wrapper = AutoEditorWrapper()
    success = wrapper.run_smart_cut(
        input_path=input_file,
        output_path=output_file,
        margin="0.3s",
        threshold=0.05,
        silent_speed=99999.0
    )

    assert success is True
    mock_run.assert_called_once()
    
    # 呼び出し時の引数の検証
    cmd = mock_run.call_args[0][0]
    assert cmd[0:3] == ["python", "-m", "auto_editor"]
    assert str(input_file) in cmd
    assert "--edit" in cmd
    assert "audio:threshold=0.05" in cmd
    assert "--margin" in cmd
    assert "0.3s" in cmd
    assert "--when-silent" in cmd
    assert "cut" in cmd
    assert "--output" in cmd
    assert str(output_file) in cmd


def test_run_smart_cut_file_not_found(tmp_path):
    """入力ファイルが存在しない場合に FileNotFoundError をスローすることを確認"""
    input_file = tmp_path / "non_existent.mp4"
    output_file = tmp_path / "dummy_output.mp4"

    wrapper = AutoEditorWrapper()
    with pytest.raises(FileNotFoundError):
        wrapper.run_smart_cut(input_file, output_file)


@patch("backend.video_pipeline.auto_editor_wrapper.AutoEditorWrapper._run_command")
def test_run_smart_cut_failed(mock_run, tmp_path):
    """auto-editorコマンド失敗時に例外をスローすることを確認"""
    input_file = tmp_path / "dummy_input.mp4"
    output_file = tmp_path / "dummy_output.mp4"
    input_file.write_text("dummy video content")

    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["auto-editor"],
        output="",
        stderr="Error: Invalid codec"
    )

    wrapper = AutoEditorWrapper()
    with pytest.raises(subprocess.CalledProcessError):
        wrapper.run_smart_cut(input_file, output_file)
