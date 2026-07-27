import pytest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
import shutil
import runpy
import logging
import sys

# backend ディレクトリと backend/services を sys.path に追加してインポートエラーを防ぐ
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
services_dir = backend_dir / "services"
if str(services_dir) not in sys.path:
    sys.path.insert(0, str(services_dir))

from backend.integrated_preview import create_integrated_preview_with_subtitle

def test_create_integrated_preview_success(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    # 呼び出し時の ffmpeg コマンド等をモック化しつつ、ダミーの出力ファイルを生成する
    mock_run = MagicMock()
    
    def side_effect(cmd, **kwargs):
        if "ffmpeg" in cmd:
            out_file = cmd[-1]
            Path(out_file).parent.mkdir(parents=True, exist_ok=True)
            Path(out_file).touch()
        return subprocess.CompletedProcess(cmd, 0)
        
    mock_run.side_effect = side_effect
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        
        def apply_overlay_side_effect(input_video, output_path, **kwargs):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).touch()
            
        mock_overlay.apply_brand_overlay.side_effect = apply_overlay_side_effect
        
        res = create_integrated_preview_with_subtitle(
            input_video=input_video,
            subtitle_file=subtitle_file,
            output_path=output_path,
            logo_height=45,
            design_name="TestDesign"
        )
        
        assert res == output_path
        assert Path(output_path).exists()
        assert mock_run.call_count == 2
        mock_overlay.apply_brand_overlay.assert_called_once()
        
        # クリーンアップ
        shutil.rmtree("backend/temp/integrated", ignore_errors=True)

def test_create_integrated_preview_subtitle_burn_failure(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    mock_run = MagicMock()
    
    call_idx = 0
    def side_effect(cmd, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            out_file = cmd[-1]
            Path(out_file).parent.mkdir(parents=True, exist_ok=True)
            Path(out_file).touch()
            return subprocess.CompletedProcess(cmd, 0)
        else:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=cmd,
                stderr="Mock FFmpeg error burning subtitles"
            )
            
    mock_run.side_effect = side_effect
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        
        def apply_overlay_side_effect(input_video, output_path, **kwargs):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).touch()
            
        mock_overlay.apply_brand_overlay.side_effect = apply_overlay_side_effect
        
        res = create_integrated_preview_with_subtitle(
            input_video=input_video,
            subtitle_file=subtitle_file,
            output_path=output_path,
            logo_height=45,
            design_name="TestDesign"
        )
        
        assert res == output_path
        assert Path(output_path).exists()
        assert any("字幕焼き込み失敗" in record.message for record in caplog.records)
        
        # クリーンアップ
        shutil.rmtree("backend/temp/integrated", ignore_errors=True)

def test_main_block_file_exists():
    from backend.integrated_preview import main
    with patch("backend.integrated_preview.Path.exists", return_value=True), \
         patch("backend.integrated_preview.create_integrated_preview_with_subtitle") as mock_create:
        
        main()
        mock_create.assert_called_once()

def test_main_block_file_not_exists():
    from backend.integrated_preview import main
    with patch("backend.integrated_preview.Path.exists", return_value=False), \
         patch("backend.integrated_preview.create_integrated_preview_with_subtitle") as mock_create:
        
        main()
        mock_create.assert_not_called()

def test_create_integrated_preview_extraction_failure(tmp_path):
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    mock_run = MagicMock()
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd="ffmpeg",
        stderr="Mock FFmpeg extraction error"
    )
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        
        with pytest.raises(subprocess.CalledProcessError):
            create_integrated_preview_with_subtitle(
                input_video=input_video,
                subtitle_file=subtitle_file,
                output_path=output_path,
                logo_height=45,
                design_name="TestDesign"
            )

def test_create_integrated_preview_overlay_failure(tmp_path):
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    mock_run = MagicMock()
    # 最初の10秒切り出しは成功するようにする
    mock_run.return_value = subprocess.CompletedProcess("ffmpeg", 0)
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        mock_overlay.apply_brand_overlay.side_effect = RuntimeError("Mock overlay runtime error")
        
        with pytest.raises(RuntimeError):
            create_integrated_preview_with_subtitle(
                input_video=input_video,
                subtitle_file=subtitle_file,
                output_path=output_path,
                logo_height=45,
                design_name="TestDesign"
            )


def test_create_integrated_preview_invalid_logo_height(tmp_path):
    # logo_height に None や文字列、負の値を渡すエッジケース
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess("ffmpeg", 0)
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        
        # 1. 負の整数
        create_integrated_preview_with_subtitle(
            input_video=input_video, subtitle_file=subtitle_file, output_path=output_path,
            logo_height=-10
        )
        assert mock_overlay.apply_brand_overlay.call_args[1]["logo_height"] == -10
        
        # 2. None
        create_integrated_preview_with_subtitle(
            input_video=input_video, subtitle_file=subtitle_file, output_path=output_path,
            logo_height=None
        )
        assert mock_overlay.apply_brand_overlay.call_args[1]["logo_height"] is None
        
        # 3. 不正な文字列型
        create_integrated_preview_with_subtitle(
            input_video=input_video, subtitle_file=subtitle_file, output_path=output_path,
            logo_height="invalid_height"
        )
        assert mock_overlay.apply_brand_overlay.call_args[1]["logo_height"] == "invalid_height"


def test_create_integrated_preview_empty_paths(tmp_path):
    # パスが空文字列の場合のエッジケース
    input_video = ""
    subtitle_file = ""
    output_path = ""
    
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess("ffmpeg", 0)
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        
        res = create_integrated_preview_with_subtitle(
            input_video=input_video, subtitle_file=subtitle_file, output_path=output_path
        )
        assert res == ""


def test_create_integrated_preview_extreme_design_name(tmp_path):
    # design_name に非常に長い文字列や特殊文字を渡すエッジケース
    input_video = str(tmp_path / "input.mp4")
    subtitle_file = str(tmp_path / "sub.srt")
    output_path = str(tmp_path / "output.mp4")
    
    mock_run = MagicMock()
    mock_run.return_value = subprocess.CompletedProcess("ffmpeg", 0)
    
    extreme_name = "A" * 1000 + "\n\t!@#$%^&*()_+{}|:<>?"
    
    with patch("backend.integrated_preview.subprocess.run", mock_run), \
         patch("combined_overlay.CombinedOverlay") as mock_overlay_cls:
        mock_overlay = MagicMock()
        mock_overlay_cls.return_value = mock_overlay
        
        res = create_integrated_preview_with_subtitle(
            input_video=input_video, subtitle_file=subtitle_file, output_path=output_path,
            design_name=extreme_name
        )
        assert res == output_path


