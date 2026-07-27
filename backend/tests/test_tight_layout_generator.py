import pytest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
from PIL import Image
import logging

from tight_layout_generator import create_tight_layout_preview, _run_ffmpeg_command


def test_run_ffmpeg_command_success():
    """_run_ffmpeg_command の成功時の動作をテスト"""
    mock_result = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout="success", stderr="")
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        res = _run_ffmpeg_command(["ffmpeg", "-version"], "version_check")
        assert res.returncode == 0
        mock_run.assert_called_once()


def test_run_ffmpeg_command_error():
    """_run_ffmpeg_command の失敗時（CalledProcessError）の動作をテスト"""
    error = subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], output="out", stderr="err")
    with patch("subprocess.run", side_effect=error) as mock_run:
        with pytest.raises(subprocess.CalledProcessError):
            _run_ffmpeg_command(["ffmpeg"], "fail_test")
        mock_run.assert_called_once()


def test_run_ffmpeg_command_not_found():
    """_run_ffmpeg_command の ffmpeg 不在（FileNotFoundError）時の動作をテスト"""
    error = FileNotFoundError("No such file or directory")
    with patch("subprocess.run", side_effect=error) as mock_run:
        with pytest.raises(FileNotFoundError):
            _run_ffmpeg_command(["ffmpeg"], "not_found_test")


def test_create_tight_layout_preview_missing_video(tmp_path):
    """入力ビデオが見つからない場合に FileNotFoundError が発生することを確認"""
    logo_file = tmp_path / "logo.png"
    logo_file.touch()
    
    with pytest.raises(FileNotFoundError) as exc_info:
        create_tight_layout_preview(
            input_video="non_existent_video.mp4",
            logo_path=str(logo_file),
            output_dir=str(tmp_path),
            temp_dir=str(tmp_path)
        )
    assert "Input video file not found" in str(exc_info.value)


def test_create_tight_layout_preview_missing_logo(tmp_path):
    """ロゴ画像が見つからない場合に FileNotFoundError が発生することを確認"""
    video_file = tmp_path / "video.mp4"
    video_file.touch()
    
    with pytest.raises(FileNotFoundError) as exc_info:
        create_tight_layout_preview(
            input_video=str(video_file),
            logo_path="non_existent_logo.png",
            output_dir=str(tmp_path),
            temp_dir=str(tmp_path)
        )
    assert "Logo image file not found" in str(exc_info.value)


@patch("tight_layout_generator._run_ffmpeg_command")
def test_create_tight_layout_preview_success(mock_run_ffmpeg, tmp_path):
    """正常系の動作確認（FFmpeg呼び出しとPIL処理をモック）"""
    video_file = tmp_path / "video.mp4"
    video_file.touch()
    
    logo_file = tmp_path / "logo.png"
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    img.save(logo_file)
    
    final_video = create_tight_layout_preview(
        input_video=str(video_file),
        logo_path=str(logo_file),
        output_dir=str(tmp_path),
        temp_dir=str(tmp_path)
    )
    
    assert Path(final_video).name == "tight_layout.mp4"
    assert (tmp_path / "telop_tight.png").exists()
    assert mock_run_ffmpeg.call_count == 6
