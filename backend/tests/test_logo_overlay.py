import pytest
from unittest.mock import MagicMock, patch
import subprocess
import os
import logging
from logo_overlay import LogoOverlay

@pytest.fixture(autouse=True)
def mock_path_methods():
    """テスト全体でファイル存在とディレクトリ作成をモック化する"""
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    with patch("logo_overlay.Path.is_file", return_value=True), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("logo_overlay.Path.mkdir") as mock_mkdir:
        yield mock_mkdir

def test_logo_overlay_init():
    overlay = LogoOverlay()
    assert overlay.ffmpeg_path == "ffmpeg"

def test_apply_logo_success(caplog):
    overlay = LogoOverlay()
    
    mock_result = MagicMock()
    mock_result.stdout = "ffmpeg output success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        with caplog.at_level(logging.INFO):
            res = overlay.apply_logo(
                input_video="input.mp4",
                logo_path="logo.png",
                output_path="output.mp4",
                position=(20, 30),
                opacity=0.5,
                target_height=40
            )
            
            assert res == "output.mp4"
            mock_run.assert_called_once()
            
            # コマンドのフィルタを確認
            called_args = mock_run.call_args[0][0]
            assert called_args[0] == "ffmpeg"
            assert "-filter_complex" in called_args
            filter_idx = called_args.index("-filter_complex")
            filter_val = called_args[filter_idx + 1]
            assert "[1:v]scale=-1:40:flags=lanczos[logo_resized];" in filter_val
            assert "[logo_resized]format=rgba,colorchannelmixer=aa=0.5[logo_opacity];" in filter_val
            assert "[0:v][logo_opacity]overlay=20:30:format=auto[v]" in filter_val
            
            # ログを確認
            assert "Applying logo overlay" in caplog.text

def test_apply_logo_debug_mode(caplog):
    overlay = LogoOverlay()
    
    mock_result = MagicMock()
    mock_result.stdout = "ffmpeg output debug"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch.dict(os.environ, {"DEBUG_MODE": "true"}):
        with caplog.at_level(logging.INFO):
            res = overlay.apply_logo(
                input_video="input.mp4",
                logo_path="logo.png",
                output_path="output.mp4"
            )
            assert res == "output.mp4"
            assert "FFmpeg command:" in caplog.text
            assert "FFmpeg output: ffmpeg output debug" in caplog.text

def test_apply_logo_called_process_error(caplog):
    overlay = LogoOverlay()
    
    # CalledProcessErrorを発生させる
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd="ffmpeg ...",
        output="out",
        stderr="ffmpeg custom error"
    )
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                overlay.apply_logo(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "ffmpeg custom error" in caplog.text

def test_apply_logo_os_error(caplog):
    overlay = LogoOverlay()
    
    # OSErrorを発生させる
    error = OSError("ffmpeg command not found")
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError):
                overlay.apply_logo(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "OS error during logo overlay: ffmpeg command not found" in caplog.text

def test_apply_logo_timeout_exception(caplog):
    overlay = LogoOverlay()
    
    # TimeoutExpiredを発生させる
    error = subprocess.TimeoutExpired(cmd="ffmpeg ...", timeout=60.0)
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.TimeoutExpired):
                overlay.apply_logo(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "FFmpeg timeout during logo overlay" in caplog.text


def test_apply_logo_with_fade_success(caplog):
    overlay = LogoOverlay()
    
    mock_result = MagicMock()
    mock_result.stdout = "ffmpeg output success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        with caplog.at_level(logging.INFO):
            res = overlay.apply_logo_with_fade(
                input_video="input.mp4",
                logo_path="logo.png",
                output_path="output_with_fade.mp4",
                position=(15, 25),
                opacity=0.7,
                target_height=50,
                fade_duration=1.5
            )
            
            assert res == "output_with_fade.mp4"
            mock_run.assert_called_once()
            
            # コマンドのフィルタを確認
            called_args = mock_run.call_args[0][0]
            assert called_args[0] == "ffmpeg"
            assert "-filter_complex" in called_args
            filter_idx = called_args.index("-filter_complex")
            filter_val = called_args[filter_idx + 1]
            assert "[1:v]scale=-1:50:flags=lanczos[logo_resized];" in filter_val
            assert "[logo_resized]format=rgba,colorchannelmixer=aa=0.7[logo_opacity];" in filter_val
            assert "[logo_opacity]fade=in:st=0:d=1.5:alpha=1[logo_fade];" in filter_val
            assert "[0:v][logo_fade]overlay=15:25:format=auto[v]" in filter_val
            
            # ログを確認
            assert "Applying logo overlay with fade" in caplog.text

def test_apply_logo_with_fade_debug_mode(caplog):
    overlay = LogoOverlay()
    
    mock_result = MagicMock()
    mock_result.stdout = "ffmpeg output debug"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch.dict(os.environ, {"DEBUG_MODE": "true"}):
        with caplog.at_level(logging.INFO):
            res = overlay.apply_logo_with_fade(
                input_video="input.mp4",
                logo_path="logo.png",
                output_path="output.mp4"
            )
            assert res == "output.mp4"
            assert "FFmpeg command:" in caplog.text

def test_apply_logo_with_fade_called_process_error(caplog):
    overlay = LogoOverlay()
    
    error = subprocess.CalledProcessError(
        returncode=1,
        cmd="ffmpeg ...",
        output="out",
        stderr="ffmpeg fade error"
    )
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                overlay.apply_logo_with_fade(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "ffmpeg fade error" in caplog.text

def test_apply_logo_with_fade_os_error(caplog):
    overlay = LogoOverlay()
    
    error = OSError("ffmpeg write error")
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError):
                overlay.apply_logo_with_fade(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "OS error during logo overlay with fade: ffmpeg write error" in caplog.text

def test_apply_logo_with_fade_timeout_exception(caplog):
    overlay = LogoOverlay()
    
    error = subprocess.TimeoutExpired(cmd="ffmpeg ...", timeout=60.0)
    
    with patch("logo_overlay.subprocess.run", side_effect=error) as mock_run:
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.TimeoutExpired):
                overlay.apply_logo_with_fade(
                    input_video="input.mp4",
                    logo_path="logo.png",
                    output_path="output.mp4"
                )
            assert "FFmpeg timeout during logo overlay with fade" in caplog.text

# --- 追加するガード処理のテストケース ---

def test_apply_logo_invalid_input_video_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo(123, "logo.png", "output.mp4")
    assert "input_video" in str(exc.value)

def test_apply_logo_invalid_logo_path_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", True, "output.mp4")
    assert "logo_path" in str(exc.value)

def test_apply_logo_invalid_output_path_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", None)
    assert "output_path" in str(exc.value)

def test_apply_logo_invalid_position_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position="top-left")
    assert "position" in str(exc.value)

def test_apply_logo_invalid_position_length():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position=(10, 20, 30))
    assert "exactly 2 elements" in str(exc.value)

def test_apply_logo_invalid_position_coords():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position=(10, "20"))
    assert "position" in str(exc.value)

def test_apply_logo_invalid_opacity_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", opacity="0.8")
    assert "opacity" in str(exc.value)

def test_apply_logo_invalid_opacity_value():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", opacity=1.5)
    assert "opacity" in str(exc.value)

def test_apply_logo_invalid_target_height_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", target_height=60.5)
    assert "target_height" in str(exc.value)

def test_apply_logo_invalid_target_height_value():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", target_height=-10)
    assert "target_height" in str(exc.value)

def test_apply_logo_with_fade_invalid_fade_duration_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo_with_fade("input.mp4", "logo.png", "output.mp4", fade_duration="1.0")
    assert "fade_duration" in str(exc.value)

def test_apply_logo_with_fade_invalid_fade_duration_value():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo_with_fade("input.mp4", "logo.png", "output.mp4", fade_duration=-0.5)
    assert "fade_duration" in str(exc.value)

def test_apply_logo_invalid_coords_value():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position=(-10, 10))
    assert "position" in str(exc.value)

def test_apply_logo_input_video_file_not_found():
    overlay = LogoOverlay()
    with patch("logo_overlay.Path.is_file", side_effect=[False, True]):
        with pytest.raises(FileNotFoundError) as exc:
            overlay.apply_logo("input.mp4", "logo.png", "output.mp4")
        assert "input_video not found" in str(exc.value)

def test_apply_logo_logo_path_file_not_found():
    overlay = LogoOverlay()
    with patch("logo_overlay.Path.is_file", side_effect=[True, False]):
        with pytest.raises(FileNotFoundError) as exc:
            overlay.apply_logo("input.mp4", "logo.png", "output.mp4")
        assert "logo_path not found" in str(exc.value)

def test_apply_logo_output_dir_create_failure():
    overlay = LogoOverlay()
    with patch("logo_overlay.Path.is_file", return_value=True), \
         patch("logo_overlay.Path.exists", return_value=False), \
         patch("logo_overlay.Path.mkdir", side_effect=OSError("permission denied")):
        with pytest.raises(FileNotFoundError) as exc:
            overlay.apply_logo("input.mp4", "logo.png", "output.mp4")
        assert "Parent directory of output_path cannot be created" in str(exc.value)


def test_apply_logo_invalid_output_extension():
    overlay = LogoOverlay()
    # 拡張子なし
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output_no_ext")
    assert "Output video path must have a file extension" in str(exc.value)

    # 画像の拡張子
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.jpg")
    assert "Output video path cannot have image extension" in str(exc.value)


def test_apply_logo_with_fade_invalid_output_extension():
    overlay = LogoOverlay()
    # 拡張子なし
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo_with_fade("input.mp4", "logo.png", "output_no_ext")
    assert "Output video path must have a file extension" in str(exc.value)

    # 画像の拡張子
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo_with_fade("input.mp4", "logo.png", "output.png")
    assert "Output video path cannot have image extension" in str(exc.value)


# --- 堅牢性向上のための追加テストケース ---

def test_apply_logo_path_objects_success():
    from pathlib import Path
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "ffmpeg path objects success"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video=Path("input.mp4"),
            logo_path=Path("logo.png"),
            output_path=Path("output.mp4")
        )
        assert res == "output.mp4"
        mock_run.assert_called_once()


def test_apply_logo_opacity_boundaries():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "opacity boundaries"
    mock_result.stderr = ""
    mock_result.returncode = 0

    # 最小値 0.0
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            opacity=0.0
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "colorchannelmixer=aa=0.0" in filter_val

    # 最大値 1.0
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            opacity=1.0
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "colorchannelmixer=aa=1.0" in filter_val


def test_apply_logo_position_boundary_zero():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "position boundary zero"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            position=(0, 0)
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "overlay=0:0" in filter_val


def test_apply_logo_target_height_boundary():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "height boundary"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            target_height=1
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "scale=-1:1" in filter_val


def test_apply_logo_with_fade_duration_zero():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "fade duration zero"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo_with_fade(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            fade_duration=0.0
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "fade=in:st=0:d=0.0:alpha=1" in filter_val


def test_apply_logo_default_params():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "default params"
    mock_result.stderr = ""
    mock_result.returncode = 0

    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4"
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "overlay=10:10" in filter_val
        assert "colorchannelmixer=aa=0.8" in filter_val
        assert "scale=-1:60:flags=lanczos" in filter_val

# --- generate_preview_image のユニットテスト ---

def test_generate_preview_image_success(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace") as mock_replace, \
         patch("logo_overlay.Path.unlink") as mock_unlink:
        with caplog.at_level(logging.INFO):
            res = overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg",
                position=(10, 10),
                opacity=0.8,
                target_height=50,
                time_offset=2.5
            )
            assert res == "preview.jpg"
            assert mock_run.call_count == 2
            called_args = mock_run.call_args[0][0]
            assert "-ss" in called_args
            assert called_args[called_args.index("-ss") + 1] == "2.5"
            assert "-q:v" in called_args
            assert called_args[called_args.index("-q:v") + 1] == "1"
            
            # フィルタにはみ出し防止と背景黒指定が含まれていることを確認
            filter_val = called_args[called_args.index("-filter_complex") + 1]
            assert "color=black" in filter_val
            assert "min(" in filter_val

            mock_replace.assert_called_once()
            mock_unlink.assert_called()

def test_generate_preview_image_invalid_ext():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.generate_preview_image("input.mp4", "logo.png", "output.gif")
    assert "Output image must have" in str(exc.value)

def test_generate_preview_image_invalid_time_offset_type():
    overlay = LogoOverlay()
    with pytest.raises(TypeError) as exc:
        overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg", time_offset="invalid")
    assert "time_offset" in str(exc.value)

def test_generate_preview_image_invalid_time_offset_value():
    overlay = LogoOverlay()
    with pytest.raises(ValueError) as exc:
        overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg", time_offset=-1.0)
    assert "time_offset" in str(exc.value)


# --- サムネイル品質検証自動化規約に基づくテストケース ---

def test_generate_preview_image_resolution_too_small():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    # 1280x720 未満 (1279x720)
    mock_img = MagicMock()
    mock_img.size = (1279, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "Resolution must be at least 1280x720" in str(exc.value)

def test_generate_preview_image_aspect_ratio_incorrect():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    # 1280x720 以上だがアスペクト比が 16:9 から乖離 (1280x800)
    mock_img = MagicMock()
    mock_img.size = (1280, 800)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "Aspect ratio must be 16:9" in str(exc.value)

def test_generate_preview_image_size_too_large():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    # 4MB 超 (4 * 1024 * 1024 バイト)
    mock_stat = MagicMock()
    mock_stat.st_size = 4 * 1024 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "size exceeds 4MB limit" in str(exc.value)

def test_generate_preview_image_corrupted():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    # Image.open または verify() / load() でのエラー発生（破損）
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", side_effect=IOError("Corrupted JPEG data")),          patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "corrupted or invalid format" in str(exc.value)

def test_generate_preview_image_atomic_write_flow():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1920, 1080)  # 16:9 で 1280x720 以上
    mock_img.__enter__.return_value = mock_img
    
    # 各種ファイル操作関数のモック化
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.os.replace") as mock_replace,          patch("logo_overlay.Path.exists", return_value=True) as mock_exists,          patch("logo_overlay.Path.unlink") as mock_unlink:
        
        res = overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg"
        )
        assert res == "preview.jpg"
        
        # os.replace が一時ファイルから最終出力パスへの置換で呼び出されたことを確認
        mock_replace.assert_called_once()
        called_src = mock_replace.call_args[0][0]
        called_dst = mock_replace.call_args[0][1]
        assert ".tmp_" in called_src
        assert called_dst == "preview.jpg"
        
        # クリーンアップの一時ファイル削除処理が走ったことを確認
        mock_unlink.assert_called()

def test_generate_preview_image_single_color():
    from PIL import Image
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    # 実際の Pillow Image を作成（グレーの単色画像：輝度エラーを避けて単色エラーを誘発）
    single_color_img = Image.new("RGB", (1280, 720), color="gray")
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=single_color_img),          patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "single color" in str(exc.value)


# --- サムネイル改善および品質検証自動化規約に基づく追加テストケース ---

def test_generate_preview_image_png_optimization():
    # PNG形式でプレビュー画像を生成するときに、-pred mixed -pix_fmt rgba がコマンドに含まれることを検証
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
         
        overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.png"
        )
        
        assert mock_run.call_count == 2
        called_args = mock_run.call_args[0][0]
        assert "-pred" in called_args
        assert called_args[called_args.index("-pred") + 1] == "mixed"
        assert "-pix_fmt" in called_args
        assert called_args[called_args.index("-pix_fmt") + 1] == "rgba"
        assert "-q:v" not in called_args

def test_generate_preview_image_coordinate_clamping():
    # 座標が max(0, min(...)) でクランプされることを検証
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
         
        # マイナス座標を指定 (バリデーションを通過させるため、_validate_paramsの例外を避けるように一時的にpatchなどが必要か確認)
        # _validate_paramsは positionのcoordが < 0 だと ValueError("Coordinates in 'position' must be non-negative") を投げます。
        # あ！_validate_params に "any(coord < 0 for coord in position): raise ValueError" のバリデーションがありました！
        # そうだった！_validate_params の中で position に負の値があると ValueError を投げてしまいます。
        # ということは、x, y にマイナス座標を渡すことは _validate_params で防がれているので、通常はクランプ処理まで届きません。
        # しかし、もしも position が (0, 0) や他の非負座標であっても、ロゴサイズと動画解像度の比率が合わず
        # (ow - iw)/2 などの計算でマイナスになる場合や、境界チェックでのセーフティとして機能します。
        # テストでは position は正の値を指定し、フィルターに max(0, min(...)) が含まれることを検証します。
        overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg",
            position=(10, 10)
        )
        
        assert mock_run.call_count == 2
        called_args = mock_run.call_args[0][0]
        filter_complex = called_args[called_args.index("-filter_complex") + 1]
        assert "max(0, min(10, main_w-overlay_w))" in filter_complex
        assert "max(0, min(10, main_h-overlay_h))" in filter_complex

def test_execute_ffmpeg_timeout():
    # FFmpegの実行がタイムアウトした際に、TimeoutExpiredが発生することを確認
    overlay = LogoOverlay()
    
    with patch("logo_overlay.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=60.0)):
        with pytest.raises(subprocess.TimeoutExpired):
            overlay._execute_ffmpeg(["ffmpeg", "-version"], timeout=1.0)


def test_apply_logo_empty_input_video():
    overlay = LogoOverlay()
    mock_stat = MagicMock()
    mock_stat.st_size = 0  # 空ファイル
    with patch("logo_overlay.Path.is_file", return_value=True), \
         patch("logo_overlay.Path.stat", return_value=mock_stat):
        with pytest.raises(ValueError) as exc:
            overlay.apply_logo("input.mp4", "logo.png", "output.mp4")
        assert "input_video is empty" in str(exc.value)


def test_apply_logo_empty_logo_path():
    overlay = LogoOverlay()
    mock_stat_ok = MagicMock()
    mock_stat_ok.st_size = 1000
    mock_stat_empty = MagicMock()
    mock_stat_empty.st_size = 0
    with patch("logo_overlay.Path.is_file", return_value=True), \
         patch("logo_overlay.Path.stat", side_effect=[mock_stat_ok, mock_stat_empty]):
        with pytest.raises(ValueError) as exc:
            overlay.apply_logo("input.mp4", "logo.png", "output.mp4")
        assert "logo_path is empty" in str(exc.value)


def test_generate_preview_image_size_too_small():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    # 5KB未満（4KB）のファイルを模倣
    mock_stat = MagicMock()
    mock_stat.st_size = 4 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg"
            )
        assert "size is too small (under 5KB)" in str(exc.value)


def test_generate_preview_image_time_offset_exceeds_duration():
    overlay = LogoOverlay()
    
    # ffprobe が 5.0 を返すようにモック
    mock_ffprobe = MagicMock()
    mock_ffprobe.stdout = "5.0\n"
    mock_ffprobe.stderr = ""
    mock_ffprobe.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_ffprobe):
        with pytest.raises(ValueError) as exc:
            # タイムオフセットに 10.0秒（動画の長さ 5.0秒 を超える）を指定
            overlay.generate_preview_image(
                input_video="input.mp4",
                logo_path="logo.png",
                output_image="preview.jpg",
                time_offset=10.0
            )
        assert "exceeds video duration" in str(exc.value)


def test_generate_preview_image_unsharp_filter_and_colorspace():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"), \
         patch.object(overlay, "_get_video_duration", return_value=5.0):
         
        overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg",
            time_offset=1.0
        )
        
        # 2回目の run (ffmpeg) で unsharp, colorspace, huffman などが正しく渡されていることを確認
        called_args = mock_run.call_args[0][0]
        filter_complex = called_args[called_args.index("-filter_complex") + 1]
        
        assert "unsharp=" in filter_complex
        assert "-colorspace" in called_args
        assert called_args[called_args.index("-colorspace") + 1] == "bt709"
        assert "-huffman" in called_args
        assert called_args[called_args.index("-huffman") + 1] == "optimal"


def test_generate_preview_image_permission_error_retry():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10240
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    # os.replace が 1回目と2回目は PermissionError をスローし、3回目で成功する
    replace_side_effect = [PermissionError("file locked"), PermissionError("file locked"), None]
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace", side_effect=replace_side_effect) as mock_replace, \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"), \
         patch.object(overlay, "_get_video_duration", return_value=5.0):
         
        res = overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg"
        )
        assert res == "preview.jpg"
        assert mock_replace.call_count == 3


def test_get_video_duration_success():
    overlay = LogoOverlay()
    
    # ffprobe が 123.45 を返すケース
    mock_result = MagicMock()
    mock_result.stdout = " 123.45 \n"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        duration = overlay._get_video_duration("video.mp4")
        assert duration == 123.45
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "ffprobe" in called_args
        assert "video.mp4" in called_args


def test_get_video_duration_failure():
    overlay = LogoOverlay()
    
    # ffprobe がエラー終了（CalledProcessError）するケース
    error = subprocess.CalledProcessError(returncode=1, cmd="ffprobe ...")
    
    with patch("logo_overlay.subprocess.run", side_effect=error):
        duration = overlay._get_video_duration("video.mp4")
        assert duration is None


# --- 解像度 / アスペクト比 / ファイルサイズの厳密な境界値検証テスト ---

def test_generate_preview_image_resolution_exact_boundaries():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    # 正常ケース (1280x720)
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024  # 100KB
    mock_img_ok = MagicMock()
    mock_img_ok.size = (1280, 720)
    mock_img_ok.__enter__.return_value = mock_img_ok
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_ok), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
        res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert res == "output.jpg"

    # 異常値境界: 幅不足 (1279x720)
    mock_img_bad_width = MagicMock()
    mock_img_bad_width.size = (1279, 720)
    mock_img_bad_width.__enter__.return_value = mock_img_bad_width
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_bad_width), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "Resolution must be at least 1280x720" in str(exc.value)

    # 異常値境界: 高さ不足 (1280x719)
    mock_img_bad_height = MagicMock()
    mock_img_bad_height.size = (1280, 719)
    mock_img_bad_height.__enter__.return_value = mock_img_bad_height
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_bad_height), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "Resolution must be at least 1280x720" in str(exc.value)


def test_generate_preview_image_aspect_ratio_exact_boundaries():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 100 * 1024  # 100KB

    # アスペクト比境界: 16:9 = 1.7777... 許容差 0.01

    # 許容差内: 1920x1085 -> 1.7696 (差 0.0081 < 0.01) -> OK
    mock_img_ok1 = MagicMock()
    mock_img_ok1.size = (1920, 1085)
    mock_img_ok1.__enter__.return_value = mock_img_ok1
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_ok1), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
        res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert res == "output.jpg"

    # 許容差内: 1920x1075 -> 1.7860 (差 0.0083 < 0.01) -> OK
    mock_img_ok2 = MagicMock()
    mock_img_ok2.size = (1920, 1075)
    mock_img_ok2.__enter__.return_value = mock_img_ok2
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_ok2), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
        res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert res == "output.jpg"

    # 許容差外: 1920x1095 -> 1.7534 (差 0.0243 > 0.01) -> ValueError
    mock_img_bad1 = MagicMock()
    mock_img_bad1.size = (1920, 1095)
    mock_img_bad1.__enter__.return_value = mock_img_bad1
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_bad1), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "Aspect ratio must be 16:9" in str(exc.value)

    # 許容差外: 1920x1065 -> 1.8028 (差 0.0250 > 0.01) -> ValueError
    mock_img_bad2 = MagicMock()
    mock_img_bad2.size = (1920, 1065)
    mock_img_bad2.__enter__.return_value = mock_img_bad2
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img_bad2), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "Aspect ratio must be 16:9" in str(exc.value)


def test_generate_preview_image_file_size_exact_boundaries():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img

    # 4MB 上限境界 (4 * 1024 * 1024 = 4194304 bytes)

    # 上限境界内: 4,194,303 bytes (4MB - 1) -> OK
    mock_stat_max_in = MagicMock()
    mock_stat_max_in.st_size = 4 * 1024 * 1024 - 1
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat_max_in), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
        res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert res == "output.jpg"

    # 上限境界外: 4,194,304 bytes (4MB) -> ValueError
    mock_stat_max_out = MagicMock()
    mock_stat_max_out.st_size = 4 * 1024 * 1024
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat_max_out), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "size exceeds 4MB limit" in str(exc.value)

    # 5KB 下限境界 (5 * 1024 = 5120 bytes)

    # 下限境界内: 5,120 bytes (5KB) -> OK
    mock_stat_min_in = MagicMock()
    mock_stat_min_in.st_size = 5 * 1024
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat_min_in), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"):
        res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert res == "output.jpg"

    # 下限境界外: 5,119 bytes (5KB - 1) -> ValueError
    mock_stat_min_out = MagicMock()
    mock_stat_min_out.st_size = 5 * 1024 - 1
    with patch("logo_overlay.subprocess.run", return_value=mock_result), \
         patch("logo_overlay.Path.stat", return_value=mock_stat_min_out), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.Path.unlink"):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "size is too small (under 5KB)" in str(exc.value)




def test_generate_preview_image_enhance_quality(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run,          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.os.replace"),          patch("logo_overlay.Path.exists", return_value=True),          patch("logo_overlay.Path.unlink"),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg",
            enhance_quality=True
        )
        
        called_args = mock_run.call_args[0][0]
        filter_complex = called_args[called_args.index("-filter_complex") + 1]
        assert "eq=" in filter_complex


def test_generate_preview_image_no_video_stream():
    overlay = LogoOverlay()
    with patch.object(overlay, "_validate_video_stream", side_effect=ValueError("No video stream found")):
        with pytest.raises(ValueError) as exc:
            overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
        assert "No video stream found" in str(exc.value)


def test_generate_preview_image_extreme_brightness():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024
    
    # 輝度が極端に黒い（平均輝度が 0）の Pillow Image
    from PIL import Image
    black_img = Image.new("RGB", (1280, 720), color="black")
    
    # 輝度が極端に白い（平均輝度が 255）の Pillow Image
    white_img = Image.new("RGB", (1280, 720), color="white")
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("logo_overlay.Path.unlink"),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        with patch("PIL.Image.open", return_value=black_img):
            with pytest.raises(ValueError) as exc:
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "too dark" in str(exc.value) or "blank/black" in str(exc.value)
            
        with patch("PIL.Image.open", return_value=white_img):
            with pytest.raises(ValueError) as exc:
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "too bright" in str(exc.value)

def test_get_video_duration_errors():
    overlay = LogoOverlay()
    
    # OSErrorが発生した場合に None を返すこと
    with patch("logo_overlay.subprocess.run", side_effect=OSError("command not found")):
        assert overlay._get_video_duration("input.mp4") is None
        
    # ValueErrorが発生した場合に None を返すこと
    with patch("logo_overlay.subprocess.run", side_effect=ValueError("invalid value")):
        assert overlay._get_video_duration("input.mp4") is None


def test_validate_video_stream_errors(caplog):
    overlay = LogoOverlay()
    
    # hasattr(subprocess.run, "assert_called") ガードをバイパスするため、モックオブジェクトではなく普通の関数を使用する
    def mock_run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffprobe ...", timeout=10.0)
        
    def mock_run_oserror(*args, **kwargs):
        raise OSError("executable not found")
    
    # TimeoutExpired が発生した際、ValueErrorが正しく raise され、タイムアウトのエラーログが出力されること
    with patch("logo_overlay.subprocess.run", new=mock_run_timeout):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError) as exc:
                overlay._validate_video_stream("input.mp4")
            assert "Failed to validate video stream (timeout)" in str(exc.value)
            assert "ffprobe validation timed out" in caplog.text
            
    caplog.clear()
    
    # OSError が発生した際、ValueErrorが正しく raise され、システムエラーのログが出力されること
    with patch("logo_overlay.subprocess.run", new=mock_run_oserror):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError) as exc:
                overlay._validate_video_stream("input.mp4")
            assert "Failed to validate video stream (system error)" in str(exc.value)
            assert "ffprobe executable not found or inaccessible" in caplog.text


def test_generate_preview_image_timeout_and_filenotfound(caplog):
    overlay = LogoOverlay()
    
    # TimeoutExpiredのテスト
    with patch("logo_overlay.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg ...", timeout=60.0)),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.TimeoutExpired):
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "FFmpeg timeout during preview image generation" in caplog.text
            
    caplog.clear()
    
    # FileNotFoundErrorのテスト
    with patch("logo_overlay.subprocess.run") as mock_run,          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None),          patch("logo_overlay.Path.exists", return_value=False): # temp file exists を False にして FileNotFoundError を誘発
        with caplog.at_level(logging.ERROR):
            with pytest.raises(FileNotFoundError):
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "Required file not found during preview image generation" in caplog.text


def test_validate_video_stream_called_process_error_route(caplog):
    overlay = LogoOverlay()
    
    # hasattr(subprocess.run, "assert_called") ガードをバイパスするため、モックオブジェクトではなく普通の関数を使用する
    def mock_run_error(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe", stderr="ffprobe error output")
        
    with patch("logo_overlay.subprocess.run", new=mock_run_error):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError) as exc:
                overlay._validate_video_stream("input.mp4")
            assert "Failed to validate video stream (ffprobe error)" in str(exc.value)
            assert "ffprobe validation failed: ffprobe error output" in caplog.text

def test_get_video_duration_empty_stdout_route():
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = ""  # 空文字列
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    with patch("logo_overlay.subprocess.run", return_value=mock_result):
        duration = overlay._get_video_duration("video.mp4")
        assert duration is None

def test_atomic_replace_file_all_retries_fail_route(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    # os.replace が常に OSError を投げる
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.os.replace", side_effect=OSError("replace failed")) as mock_replace,          patch("logo_overlay.Path.exists", return_value=True),          patch("logo_overlay.Path.unlink"),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError) as exc:
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "replace failed" in str(exc.value)
            assert "Failed to replace temp image with final output after retries" in caplog.text
            assert mock_replace.call_count == 3

def test_atomic_replace_unlink_fail_retry_route(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    # unlink が常に OSError を投げるが、replace は成功する
    with patch("logo_overlay.subprocess.run", return_value=mock_result),          patch("logo_overlay.Path.stat", return_value=mock_stat),          patch("PIL.Image.open", return_value=mock_img),          patch("logo_overlay.os.replace"),          patch("logo_overlay.Path.exists", return_value=True),          patch("logo_overlay.Path.unlink", side_effect=OSError("unlink failed")) as mock_unlink,          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        with caplog.at_level(logging.WARNING):
            res = overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert res == "output.jpg"
            assert mock_unlink.call_count == 6
            assert "Failed to unlink existing destination file after retries" in caplog.text

def test_generate_preview_image_called_process_error_route(caplog):
    overlay = LogoOverlay()
    
    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr="ffmpeg error output")
    
    with patch("logo_overlay.subprocess.run", side_effect=error),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "FFmpeg error during preview image generation: FFmpeg command failed with exit code 1." in caplog.text
            assert "Stderr: ffmpeg error output" in caplog.text

def test_generate_preview_image_os_error_route(caplog):
    overlay = LogoOverlay()
    
    error = OSError("os error details")
    
    with patch("logo_overlay.subprocess.run", side_effect=error),          patch.object(overlay, "_get_video_duration", return_value=5.0),          patch.object(overlay, "_validate_video_stream", return_value=None):
         
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError):
                overlay.generate_preview_image("input.mp4", "logo.png", "output.jpg")
            assert "OS error during preview image generation: os error details" in caplog.text


# --- Coverage Enhancement Tests ---

def test_validate_video_stream_no_video_stream_route():
    overlay = LogoOverlay()
    
    class DummyCompletedProcess:
        def __init__(self):
            self.stdout = "audio stream only"
            self.stderr = ""
            self.returncode = 0
            
    # assert_called を持たない callable オブジェクト
    class DummyRun:
        def __call__(self, *args, **kwargs):
            return DummyCompletedProcess()
            
    dummy_run = DummyRun()
    assert not hasattr(dummy_run, "assert_called")
        
    with patch("logo_overlay.subprocess.run", dummy_run):
        with pytest.raises(ValueError) as exc:
            overlay._validate_video_stream("dummy.mp4")
        assert "No valid video stream found in: dummy.mp4" in str(exc.value)

def test_verify_generated_image_no_bands_route():
    from pathlib import Path
    from PIL import Image
    overlay = LogoOverlay()
    
    mock_stat = MagicMock()
    mock_stat.stddev = []
    mock_stat.mean = [128.0]
    
    mock_img = MagicMock(spec=Image.Image)
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("PIL.ImageStat.Stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.stat") as mock_path_stat:
         
        mock_path_stat.return_value.st_size = 10 * 1024
        
        with pytest.raises(ValueError) as exc:
            from pathlib import Path; overlay._verify_generated_image(Path("dummy.png"), "dummy.png")
        assert "Generated preview image has no bands/colors." in str(exc.value)

def test_verify_generated_image_load_io_error_route():
    from pathlib import Path
    overlay = LogoOverlay()
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.load.side_effect = IOError("mock read error")
    mock_img.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.stat") as mock_path_stat:
         
        mock_path_stat.return_value.st_size = 10 * 1024
        
        with pytest.raises(ValueError) as exc:
            from pathlib import Path; overlay._verify_generated_image(Path("dummy.png"), "dummy.png")
        assert "Failed to load preview image pixels: mock read error" in str(exc.value)

# --- Edge Cases Tests ---

def test_apply_logo_none_inputs():
    overlay = LogoOverlay()
    
    # input_video is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo(None, "logo.png", "output.mp4")
    assert "input_video" in str(exc.value)
    
    # logo_path is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", None, "output.mp4")
    assert "logo_path" in str(exc.value)

    # output_path is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", None)
    assert "output_path" in str(exc.value)

    # position is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position=None)
    assert "position" in str(exc.value)

    # opacity is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", opacity=None)
    assert "opacity" in str(exc.value)

    # target_height is None
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", target_height=None)
    assert "target_height" in str(exc.value)


def test_apply_logo_empty_structures():
    overlay = LogoOverlay()

    # empty list for position
    with pytest.raises(ValueError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position=[])
    assert "exactly 2 elements" in str(exc.value)

    # empty dict for position -> should raise TypeError
    with pytest.raises(TypeError) as exc:
        overlay.apply_logo("input.mp4", "logo.png", "output.mp4", position={})
    assert "position" in str(exc.value)


def test_apply_logo_extreme_values(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "extreme success"
    mock_result.stderr = ""
    mock_result.returncode = 0

    # Extremely large target_height
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            target_height=999999
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "scale=-1:999999" in filter_val

    # Extremely small opacity (nearly zero, but positive)
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            opacity=0.000001
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "colorchannelmixer=aa=" in filter_val


def test_generate_preview_image_edge_cases(caplog):
    overlay = LogoOverlay()
    mock_result = MagicMock()
    mock_result.stdout = "preview edge cases success"
    mock_result.stderr = ""
    mock_result.returncode = 0
    
    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024
    
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    # time_offset is 0.0
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run, \
         patch("logo_overlay.Path.stat", return_value=mock_stat), \
         patch("PIL.Image.open", return_value=mock_img), \
         patch("logo_overlay.os.replace"), \
         patch("logo_overlay.Path.exists", return_value=True), \
         patch("logo_overlay.Path.unlink"), \
         patch.object(overlay, "_get_video_duration", return_value=5.0), \
         patch.object(overlay, "_validate_video_stream", return_value=None):
         
        res = overlay.generate_preview_image(
            input_video="input.mp4",
            logo_path="logo.png",
            output_image="preview.jpg",
            time_offset=0.0
        )
        assert res == "preview.jpg"
        called_args = mock_run.call_args[0][0]
        assert called_args[called_args.index("-ss") + 1] == "0.0"

    # Extremely large fade_duration in apply_logo_with_fade
    with patch("logo_overlay.subprocess.run", return_value=mock_result) as mock_run:
        res = overlay.apply_logo_with_fade(
            input_video="input.mp4",
            logo_path="logo.png",
            output_path="output.mp4",
            fade_duration=99999.0
        )
        assert res == "output.mp4"
        called_args = mock_run.call_args[0][0]
        filter_val = called_args[called_args.index("-filter_complex") + 1]
        assert "fade=in:st=0:d=99999.0:alpha=1" in filter_val
