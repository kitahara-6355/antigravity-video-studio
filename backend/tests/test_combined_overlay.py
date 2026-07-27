import pytest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
import sys
import os
import logging

# backend ディレクトリと backend/services を sys.path に追加してインポートエラーを防ぐ
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
services_dir = backend_dir / "services"
if str(services_dir) not in sys.path:
    sys.path.insert(0, str(services_dir))

from combined_overlay import CombinedOverlay


def test_init():
    """初期化テスト"""
    overlay = CombinedOverlay()
    assert overlay.logo_manager is not None
    assert overlay.telop_generator is not None
    assert overlay.ffmpeg_path == "ffmpeg"


@patch("combined_overlay.subprocess.run")
def test_run_ffmpeg_success(mock_run, caplog):
    """_run_ffmpeg の正常系テスト (debug_mode 有効時含む)"""
    caplog.set_level(logging.INFO)
    mock_run.return_value = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout="success")
    overlay = CombinedOverlay()

    # debug_mode = False
    with patch.dict(os.environ, {"DEBUG_MODE": "false"}):
        res = overlay._run_ffmpeg(["ffmpeg", "-version"], "test_cmd")
        assert res.returncode == 0
        assert not any("FFmpeg command" in record.message for record in caplog.records)

    # debug_mode = True
    with patch.dict(os.environ, {"DEBUG_MODE": "true"}):
        caplog.clear()
        res = overlay._run_ffmpeg(["ffmpeg", "-version"], "test_cmd")
        assert res.returncode == 0
        assert any("FFmpeg command (test_cmd)" in record.message for record in caplog.records)


@patch("combined_overlay.subprocess.run")
def test_run_ffmpeg_failure(mock_run, caplog):
    """_run_ffmpeg の異常系テスト (エラーログ出力と再レイズ)"""
    caplog.set_level(logging.INFO)
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr="Mock FFmpeg compilation error"
    )
    overlay = CombinedOverlay()

    with pytest.raises(subprocess.CalledProcessError):
        overlay._run_ffmpeg(["ffmpeg", "-invalid"], "test_fail")
    
    assert any("FFmpeg error (test_fail): Mock FFmpeg compilation error" in record.message for record in caplog.records)


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
def test_apply_brand_overlay_logo_not_found(mock_telop_gen_cls, mock_logo_mgr_cls):
    """ロゴが見つからない場合に FileNotFoundError を発生させるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = None
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    overlay = CombinedOverlay()
    with pytest.raises(FileNotFoundError, match="Brand logo not found"):
        overlay.apply_brand_overlay(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4"
        )


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
def test_apply_brand_overlay_success(mock_run, mock_telop_gen_cls, mock_logo_mgr_cls, tmp_path):
    """apply_brand_overlay が正常に動作し、一時画像が削除されるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr.get_logo_size.return_value = (200, 100)
    mock_logo_mgr.calculate_target_size.return_value = (100, 50)
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    mock_run.return_value = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout="success")

    overlay = CombinedOverlay()
    
    # Path.unlink と Path.exists をモックして一時ファイル削除を追跡
    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        output = overlay.apply_brand_overlay(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4",
            speaker1="美麗",
            speaker2="ヒロ",
            theme="テーマ",
            logo_position=(10, 10),
            logo_height=50,
            logo_opacity=0.8,
            telop_position=None,
            telop_opacity=0.9,
            telop_duration=8.0
        )

        assert output == "dummy_output.mp4"
        mock_unlink.assert_called_once()  # 一時テロップ画像が unlink されたはず
        assert mock_run.call_count == 2


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
def test_apply_brand_overlay_cleanup_on_exception(mock_run, mock_telop_gen_cls, mock_logo_mgr_cls):
    """apply_brand_overlay 内で例外が発生した場合でも、一時ファイルが確実に削除されるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    # テロップ生成は成功するが、FFmpeg実行で例外発生
    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    mock_run.side_effect = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="error")

    overlay = CombinedOverlay()

    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        with pytest.raises(subprocess.CalledProcessError):
            overlay.apply_brand_overlay(
                input_video="dummy_input.mp4",
                output_path="dummy_output.mp4"
            )
        
        mock_unlink.assert_called_once()  # 例外時でも finally で unlink が呼ばれること


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
@patch("combined_overlay.ProgressivePreview")
@patch("combined_overlay.PreviewReportGenerator")
def test_generate_preview_success(
    mock_report_gen_cls,
    mock_preview_cls,
    mock_run,
    mock_telop_gen_cls,
    mock_logo_mgr_cls,
    tmp_path
):
    """generate_preview が正常に動作し、一時動画が削除されるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr.get_logo_size.return_value = (200, 100)
    mock_logo_mgr.calculate_target_size.return_value = (100, 50)
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    mock_run.return_value = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0)

    mock_preview = MagicMock()
    mock_preview.output_dir = tmp_path / "preview_dir"
    mock_preview_cls.return_value = mock_preview

    mock_report_gen = MagicMock()
    mock_report_gen.generate_from_session_dir.return_value = "report.html"
    mock_report_gen_cls.return_value = mock_report_gen

    overlay = CombinedOverlay()

    # exists() == True, 2回 unlink される（1回目は apply_brand_overlay 内の telop、2回目は generate_preview 内の temp_video）
    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        res = overlay.generate_preview(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4",
            preview_duration=10.0
        )
        assert res == "dummy_output.mp4"
        assert mock_run.call_count == 3
        assert mock_unlink.call_count == 2  # 2回 unlink が呼ばれる
        mock_preview.snapshot_step.assert_called_once()
        mock_report_gen.generate_from_session_dir.assert_called_once()


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
@patch("combined_overlay.ProgressivePreview")
def test_generate_preview_preview_exception_handled(
    mock_preview_cls,
    mock_run,
    mock_telop_gen_cls,
    mock_logo_mgr_cls,
    tmp_path,
    caplog
):
    """ProgressivePreview で例外が起きた場合でも、関数自体は成功し警告ログを出すテスト"""
    caplog.set_level(logging.WARNING)
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr.get_logo_size.return_value = (200, 100)
    mock_logo_mgr.calculate_target_size.return_value = (100, 50)
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    mock_run.return_value = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0)
    mock_preview_cls.side_effect = Exception("Preview system failure")

    overlay = CombinedOverlay()

    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        res = overlay.generate_preview(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4",
            preview_duration=10.0
        )
        assert res == "dummy_output.mp4"
        assert any("Preview generation failed" in record.message for record in caplog.records)


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
def test_generate_preview_extraction_failure_cleanup(
    mock_run,
    mock_telop_gen_cls,
    mock_logo_mgr_cls
):
    """動画の切り出しが失敗した場合に一時ファイルを削除して例外を投げるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_run.side_effect = Exception("FFmpeg extraction failed")

    overlay = CombinedOverlay()

    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        with pytest.raises(Exception, match="FFmpeg extraction failed"):
            overlay.generate_preview(
                input_video="dummy_input.mp4",
                output_path="dummy_output.mp4",
                preview_duration=10.0
            )
        
        mock_unlink.assert_called_once()  # finally ブロックで temp_video が unlink されること


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
def test_apply_brand_overlay_no_audio(mock_run, mock_telop_gen_cls, mock_logo_mgr_cls):
    """音声ストリームがない動画に対して apply_brand_overlay が適切にオーディオマップを外すテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr.get_logo_size.return_value = (200, 100)
    mock_logo_mgr.calculate_target_size.return_value = (100, 50)
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    # ffprobe は空出力を返して音声ストリームなしをシミュレート
    def dummy_run(cmd, *args, **kwargs):
        if "ffprobe" in cmd[0]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="success", stderr="")
        
    mock_run.side_effect = dummy_run

    overlay = CombinedOverlay()
    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        output = overlay.apply_brand_overlay(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4"
        )
        assert output == "dummy_output.mp4"
        
        # 呼ばれた ffmpeg コマンドに "-map 0:a" が含まれていないことを検証
        ffmpeg_call = mock_run.call_args_list[-1]
        ffmpeg_cmd = ffmpeg_call[0][0]
        assert "-map" in ffmpeg_cmd
        assert "0:a" not in ffmpeg_cmd


@patch("combined_overlay.LogoManager")
@patch("combined_overlay.ThemeTelopGenerator")
@patch("combined_overlay.subprocess.run")
def test_apply_brand_overlay_has_audio(mock_run, mock_telop_gen_cls, mock_logo_mgr_cls):
    """音声ストリームがある動画に対して apply_brand_overlay が適切にオーディオマップを含めるテスト"""
    mock_logo_mgr = MagicMock()
    mock_logo_mgr.get_logo_path.return_value = "/path/to/logo.png"
    mock_logo_mgr.get_logo_size.return_value = (200, 100)
    mock_logo_mgr.calculate_target_size.return_value = (100, 50)
    mock_logo_mgr_cls.return_value = mock_logo_mgr

    mock_telop_gen = MagicMock()
    mock_telop_gen.generate_video_theme_telop.return_value = "/path/to/telop.png"
    mock_telop_gen_cls.return_value = mock_telop_gen

    # ffprobe は "audio" を返して音声ストリームありをシミュレート
    def dummy_run(cmd, *args, **kwargs):
        if "ffprobe" in cmd[0]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="audio", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="success", stderr="")
        
    mock_run.side_effect = dummy_run

    overlay = CombinedOverlay()
    with patch("combined_overlay.Path.exists", return_value=True), \
         patch("combined_overlay.Path.unlink") as mock_unlink:
        
        output = overlay.apply_brand_overlay(
            input_video="dummy_input.mp4",
            output_path="dummy_output.mp4"
        )
        assert output == "dummy_output.mp4"
        
        # 呼ばれた ffmpeg コマンドに "-map 0:a" と "-c:a copy" が含まれていることを検証
        ffmpeg_call = mock_run.call_args_list[-1]
        ffmpeg_cmd = ffmpeg_call[0][0]
        assert "0:a" in ffmpeg_cmd
        assert "copy" in ffmpeg_cmd


@patch("combined_overlay.subprocess.run")
def test_has_audio_stdout_none(mock_run):
    """ffprobeの出力 res.stdout が None の場合でも例外が発生せず False を返すことを検証"""
    mock_run.return_value = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=None, stderr="")
    overlay = CombinedOverlay()
    assert overlay._has_audio("dummy.mp4") is False


@patch("combined_overlay.subprocess.run")
def test_has_audio_ffprobe_error_fallback(mock_run):
    """ffprobe実行時に例外が発生した場合にフォールバックとして True を返すことを検証"""
    mock_run.side_effect = FileNotFoundError("ffprobe not found")
    overlay = CombinedOverlay()
    assert overlay._has_audio("dummy.mp4") is True


