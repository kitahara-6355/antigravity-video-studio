"""
Unit tests for backend/screenshot_generator.py
"""

import subprocess
import pytest
import runpy
from unittest.mock import patch, MagicMock
from pathlib import Path

from backend.screenshot_generator import (
    extract_screenshot,
    generate_multiple_screenshots,
    _get_video_duration
)


def test_extract_screenshot_success(tmp_path):
    """
    extract_screenshot が正常に FFmpeg コマンドを実行して
    出力パスを返すことを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 5.5
    output_path = str(tmp_path / "output_frame.png")
    scale = "640:-1"
    
    with patch("subprocess.run") as mock_run:
        # 正常終了を模倣
        mock_run.return_value = MagicMock(returncode=0)
        
        result = extract_screenshot(video_path, timestamp, output_path, scale)
        
        assert result == output_path
        
        # 呼び出し引数の検証
        expected_cmd = [
            "ffmpeg",
            "-ss", "5.5",
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={scale}:flags=lanczos",
            "-pix_fmt", "rgb24",
            "-y",
            output_path
        ]
        mock_run.assert_called_once_with(expected_cmd, check=True, capture_output=True, timeout=30.0)



def test_extract_screenshot_failure(tmp_path):
    """
    extract_screenshot 内で FFmpeg がエラー終了した際に
    subprocess.CalledProcessError が正しく再送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 10.0
    output_path = str(tmp_path / "output_failed.png")
    
    with patch("subprocess.run") as mock_run:
        # CalledProcessError をシミュレート
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=b"FFmpeg failed dummy error"
        )
        
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            extract_screenshot(video_path, timestamp, output_path)
            
        assert exc_info.value.stderr == b"FFmpeg failed dummy error"


def test_generate_multiple_screenshots():
    """
    generate_multiple_screenshots が複数のタイムスタンプから
    スクリーンショットを生成し、正しい命名規則のパスリストを返すことを検証します。
    """
    video_path = "test_video.mp4"
    timestamps = [1.2, 4.8, 9.0]
    output_dir = "test_output_dir"
    prefix = "custom_prefix"
    
    with patch("backend.screenshot_generator.extract_screenshot") as mock_extract,          patch("pathlib.Path.mkdir") as mock_mkdir:
         
        # extract_screenshot はモックされた出力パスを返す
        mock_extract.side_effect = lambda v, t, o: o
        
        results = generate_multiple_screenshots(
            video_path=video_path,
            timestamps=timestamps,
            output_dir=output_dir,
            prefix=prefix
        )
        
        # ディレクトリ作成が呼ばれているか
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        
        # 期待される出力パス
        expected_paths = [
            str(Path(output_dir) / f"{prefix}_1_1s.png"),
            str(Path(output_dir) / f"{prefix}_2_4s.png"),
            str(Path(output_dir) / f"{prefix}_3_9s.png"),
        ]
        
        assert results == expected_paths
        assert mock_extract.call_count == len(timestamps)


def test_screenshot_generator_main_block_file_exists():
    """
    screenshot_generator の __main__ ブロックで
    動画ファイルが存在する場合の実行フローを検証します。
    """
    with patch("backend.screenshot_generator.Path.exists") as mock_exists,          patch("backend.screenshot_generator.subprocess.run") as mock_run,          patch("backend.screenshot_generator.Path.mkdir") as mock_mkdir,          patch("builtins.print") as mock_print:
         
        # パスが存在することを模擬
        mock_exists.return_value = True
        # subprocess.run の正常終了を模擬
        mock_run.return_value = MagicMock(returncode=0)
        
        # runpy で __main__ をシミュレート実行
        import sys
        orig = sys.modules.pop("backend.screenshot_generator", None)
        try:
            runpy.run_module("backend.screenshot_generator", run_name="__main__")
        finally:
            if orig is not None:
                sys.modules["backend.screenshot_generator"] = orig
        
        # subprocess.run が 3 回呼ばれていることを確認（timestamps が 3 要素なので）
        assert mock_run.call_count == 3
        # 出力結果プリントの確認
        mock_print.assert_any_call("Generated 3 screenshots")


def test_screenshot_generator_main_block_file_not_exists():
    """
    screenshot_generator の __main__ ブロックで
    動画ファイルが存在しない場合の実行フローを検証します。
    """
    with patch("backend.screenshot_generator.Path.exists") as mock_exists,          patch("backend.screenshot_generator.subprocess.run") as mock_run:
         
        mock_exists.return_value = False
        
        # runpy で __main__ をシミュレート実行
        import sys
        orig = sys.modules.pop("backend.screenshot_generator", None)
        try:
            runpy.run_module("backend.screenshot_generator", run_name="__main__")
        finally:
            if orig is not None:
                sys.modules["backend.screenshot_generator"] = orig
        
        # subprocess.run が呼ばれないことを検証
        mock_run.assert_not_called()


def test_extract_screenshot_failure_no_stderr(tmp_path):
    """
    CalledProcessError が発生し、stderr が None の場合でも
    適切にエラーハンドリングされ、CalledProcessError が再送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 10.0
    output_path = str(tmp_path / "output_failed.png")
    
    with patch("subprocess.run") as mock_run:
        # CalledProcessError をシミュレート（stderr=None）
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=None
        )
        
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            extract_screenshot(video_path, timestamp, output_path)
            
        assert exc_info.value.stderr is None


def test_generate_multiple_screenshots_empty():
    """
    timestamps が空リストの場合、空のリストを返し、
    出力ディレクトリの作成のみが行われることを検証します。
    """
    video_path = "test_video.mp4"
    timestamps = []
    output_dir = "test_output_dir"
    
    with patch("backend.screenshot_generator.extract_screenshot") as mock_extract,          patch("pathlib.Path.mkdir") as mock_mkdir:
         
        results = generate_multiple_screenshots(
            video_path=video_path,
            timestamps=timestamps,
            output_dir=output_dir
        )
        
        assert results == []
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_extract.assert_not_called()


def test_extract_screenshot_default_scale(tmp_path):
    """
    scale パラメータを省略した場合、デフォルト値の "1280:-1" が
    FFmpeg コマンドに渡されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 5.5
    output_path = str(tmp_path / "output_frame.png")
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        extract_screenshot(video_path, timestamp, output_path)
        
        # scale にデフォルト値 "1280:-1" が渡されているか確認
        expected_cmd = [
            "ffmpeg",
            "-ss", "5.5",
            "-i", video_path,
            "-vframes", "1",
            "-vf", "scale=1280:-1:flags=lanczos",
            "-pix_fmt", "rgb24",
            "-y",
            output_path
        ]
        mock_run.assert_called_once_with(expected_cmd, check=True, capture_output=True, timeout=30.0)



def test_extract_screenshot_invalid_scale_format(tmp_path):
    """
    scale に不正なフォーマットが指定された場合、FFmpeg エラーが適切にキャッチされ、
    CalledProcessError が再送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 5.5
    output_path = str(tmp_path / "output_frame.png")
    scale = "invalid_scale_format"
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=b"Invalid scale format error from ffmpeg"
        )
        
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            extract_screenshot(video_path, timestamp, output_path, scale=scale)
            
        assert b"Invalid scale format error" in exc_info.value.stderr


def test_generate_multiple_screenshots_mixed_timestamps():
    """
    timestamps に float と int が混在している場合でも、
    正常にスクリーンショットが生成され、正しい命名パスが返されることを検証します。
    """
    video_path = "test_video.mp4"
    timestamps = [1, 2.5]
    output_dir = "test_output_dir"
    
    with patch("backend.screenshot_generator.extract_screenshot") as mock_extract,          patch("pathlib.Path.mkdir") as mock_mkdir:
         
        mock_extract.side_effect = lambda v, t, o: o
        
        results = generate_multiple_screenshots(
            video_path=video_path,
            timestamps=timestamps,
            output_dir=output_dir
        )
        
        expected_paths = [
            str(Path(output_dir) / "frame_1_1s.png"),
            str(Path(output_dir) / "frame_2_2s.png"),
        ]
        assert results == expected_paths


def test_generate_multiple_screenshots_negative_timestamp():
    """
    timestamps に負の数が入っている場合でも、
    ファイル名に適切に反映され、処理が行われることを検証します。
    """
    video_path = "test_video.mp4"
    timestamps = [-1.5]
    output_dir = "test_output_dir"
    
    with patch("backend.screenshot_generator.extract_screenshot") as mock_extract,          patch("pathlib.Path.mkdir") as mock_mkdir:
         
        mock_extract.side_effect = lambda v, t, o: o
        
        results = generate_multiple_screenshots(
            video_path=video_path,
            timestamps=timestamps,
            output_dir=output_dir
        )
        
        expected_paths = [
            str(Path(output_dir) / "frame_1_-1s.png"),
        ]
        assert results == expected_paths


def test_extract_screenshot_input_validation_video_path(tmp_path):
    """
    video_path のバリデーション（None, 型エラー, 空文字列, 存在しないファイル）を検証します。
    """
    output_path = str(tmp_path / "out.png")
    
    # None の場合
    with pytest.raises(ValueError, match="video_path cannot be None"):
        extract_screenshot(None, 5.0, output_path)
        
    # 型エラーの場合
    with pytest.raises(TypeError, match="video_path must be a string"):
        extract_screenshot(12345, 5.0, output_path)
        
    # 空文字列の場合
    with pytest.raises(ValueError, match="video_path cannot be empty"):
        extract_screenshot("   ", 5.0, output_path)
        
    # 存在しないファイルの場合
    with pytest.raises(FileNotFoundError, match="Video file does not exist"):
        extract_screenshot("non_existent_video.mp4", 5.0, output_path)


def test_extract_screenshot_input_validation_timestamp(tmp_path):
    """
    timestamp のバリデーション（None, 型エラー）を検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")
    
    # None の場合
    with pytest.raises(ValueError, match="timestamp cannot be None"):
        extract_screenshot(video_path, None, output_path)
        
    # 型エラーの場合
    with pytest.raises(TypeError, match="timestamp must be a float or int"):
        extract_screenshot(video_path, "invalid_time", output_path)


def test_extract_screenshot_input_validation_output_path(tmp_path):
    """
    output_path のバリデーション（None, 型エラー, 空文字列）を検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    
    # None の場合
    with pytest.raises(ValueError, match="output_path cannot be None"):
        extract_screenshot(video_path, 5.0, None)
        
    # 型エラーの場合
    with pytest.raises(TypeError, match="output_path must be a string"):
        extract_screenshot(video_path, 5.0, 123)
        
    # 空文字列の場合
    with pytest.raises(ValueError, match="output_path cannot be empty"):
        extract_screenshot(video_path, 5.0, "  ")


def test_extract_screenshot_input_validation_scale(tmp_path):
    """
    scale のバリデーション（None, 型エラー, 空文字列）を検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")
    
    # None の場合
    with pytest.raises(ValueError, match="scale cannot be None"):
        extract_screenshot(video_path, 5.0, output_path, scale=None)
        
    # 型エラーの場合
    with pytest.raises(TypeError, match="scale must be a string"):
        extract_screenshot(video_path, 5.0, output_path, scale=999)
        
    # 空文字列の場合
    with pytest.raises(ValueError, match="scale cannot be empty"):
        extract_screenshot(video_path, 5.0, output_path, scale="")


def test_extract_screenshot_ffmpeg_not_found(tmp_path):
    """
    ffmpeg コマンドが存在しない（FileNotFoundError）場合に RuntimeError にラップされて送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")
    
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        with pytest.raises(RuntimeError, match="ffmpeg command not found"):
            extract_screenshot(video_path, 5.0, output_path)


def test_generate_multiple_screenshots_validation():
    """
    generate_multiple_screenshots の引数バリデーション（timestamps, output_dir, prefix）を検証します。
    """
    video_path = "test_video.mp4"
    
    # timestamps が None
    with pytest.raises(ValueError, match="timestamps list cannot be None"):
        generate_multiple_screenshots(video_path, None, "out_dir")
        
    # timestamps の型エラー
    with pytest.raises(TypeError, match="timestamps must be a list or tuple"):
        generate_multiple_screenshots(video_path, "not_a_list", "out_dir")
        
    # output_dir が None
    with pytest.raises(ValueError, match="output_dir cannot be None"):
        generate_multiple_screenshots(video_path, [1, 2], None)
        
    # output_dir の型エラー
    with pytest.raises(TypeError, match="output_dir must be a string"):
        generate_multiple_screenshots(video_path, [1, 2], 123)
        
    # output_dir が空文字列
    with pytest.raises(ValueError, match="output_dir cannot be empty"):
        generate_multiple_screenshots(video_path, [1, 2], "   ")
        
    # prefix が None
    with pytest.raises(ValueError, match="prefix cannot be None"):
        generate_multiple_screenshots(video_path, [1, 2], "out_dir", prefix=None)
        
    # prefix の型エラー
    with pytest.raises(TypeError, match="prefix must be a string"):
        generate_multiple_screenshots(video_path, [1, 2], "out_dir", prefix=456)
        
    # prefix が空文字列
    with pytest.raises(ValueError, match="prefix cannot be empty"):
        generate_multiple_screenshots(video_path, [1, 2], "out_dir", prefix="  ")


def test_extract_screenshot_timeout(tmp_path):
    """
    FFmpeg プロセスがタイムアウトした場合に RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30.0)
        
        with pytest.raises(RuntimeError, match="FFmpeg process timed out after 30.0 seconds"):
            extract_screenshot(video_path, 5.0, output_path, timeout=30.0)


def test_extract_screenshot_input_validation_timestamp_bool(tmp_path):
    """
    timestamp に bool 型が渡された場合に TypeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with pytest.raises(TypeError, match="timestamp must be a float or int, not bool"):
        extract_screenshot(video_path, True, output_path)

    with pytest.raises(TypeError, match="timestamp must be a float or int, not bool"):
        extract_screenshot(video_path, False, output_path)


def test_extract_screenshot_failure_stderr_types(tmp_path):
    """
    CalledProcessError が発生した際、stderr が str や None の場合でも
    AttributeError を起こさずに正しく CalledProcessError を送出することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    # stderr が str の場合
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr="String error message"
        )
        with pytest.raises(subprocess.CalledProcessError):
            extract_screenshot(video_path, 5.0, output_path)

    # stderr が None の場合 (既存テストと重複するが明示的な型比較のため再確認)
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=None
        )
        with pytest.raises(subprocess.CalledProcessError):
            extract_screenshot(video_path, 5.0, output_path)



def test_extract_screenshot_failure_invalid_utf8_stderr(tmp_path):
    """
    CalledProcessError が発生し、stderr が不正な UTF-8 バイト列の場合でも
    errors="replace" により正しく置換され、CalledProcessError が再送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 10.0
    output_path = str(tmp_path / "output_failed.png")
    
    with patch("subprocess.run") as mock_run:
        # 不正な UTF-8 バイト列 (\\xff\\xfe) をシミュレート
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=b"FFmpeg error with invalid bytes: \\xff\\xfe"
        )
        
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            extract_screenshot(video_path, timestamp, output_path)
            
        assert b"\\xff\\xfe" in exc_info.value.stderr


def test_generate_multiple_screenshots_invalid_video_path(tmp_path):
    """
    generate_multiple_screenshots を介して video_path のバリデーションエラーが
    正しく発生することを確認します。
    """
    output_dir = str(tmp_path / "screenshots")
    timestamps = [1.0, 2.0]
    
    # video_path が None
    with pytest.raises(ValueError, match="video_path cannot be None"):
        generate_multiple_screenshots(None, timestamps, output_dir)
        
    # video_path が型エラー
    with pytest.raises(TypeError, match="video_path must be a string"):
        generate_multiple_screenshots(12345, timestamps, output_dir)
        
    # video_path が空文字列
    with pytest.raises(ValueError, match="video_path cannot be empty"):
        generate_multiple_screenshots("   ", timestamps, output_dir)
        
    # video_path が存在しない
    with pytest.raises(FileNotFoundError, match="Video file does not exist"):
        generate_multiple_screenshots("non_existent_video.mp4", timestamps, output_dir)


def test_generate_multiple_screenshots_invalid_timestamp_elements(tmp_path):
    """
    generate_multiple_screenshots の timestamps リスト内に不正な値が含まれる場合、
    呼び出し過程で発生する適切な例外（int()への変換エラーや内部バリデーションエラー）を検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_dir = str(tmp_path / "screenshots")
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        # 要素が None の場合：int(None) で TypeError が発生する
        with pytest.raises(TypeError, match=r"int\(\) argument must be a string"):
            generate_multiple_screenshots(video_path, [1.0, None], output_dir)
            
        # 要素が bool 型の場合：int(True)は1になり、extract_screenshot の bool 検証で TypeError になる
        with pytest.raises(TypeError, match="timestamp must be a float or int, not bool"):
            generate_multiple_screenshots(video_path, [True], output_dir)
            
        # 要素が文字列など不正な型の場合：int("invalid") で ValueError が発生する
        with pytest.raises(ValueError, match=r"invalid literal for int\(\)"):
            generate_multiple_screenshots(video_path, [1.0, "invalid"], output_dir)


def test_screenshot_quality_resolution_aspect_ratio_and_size(tmp_path):
    """
    FFmpeg を実際に実行し、生成されたスクリーンショットの解像度、
    アスペクト比、ファイルサイズを検証します。
    """
    from PIL import Image
    
    # 1. 1920x1080のテスト用動画ファイルを生成 (デュレーション2秒)
    input_video = tmp_path / "testsrc.mp4"
    create_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=1920x1080:rate=24",
        "-c:v", "libx264",
        "-y",
        str(input_video)
    ]
    try:
        subprocess.run(create_cmd, check=True, capture_output=True, timeout=30.0)
    except FileNotFoundError:
        pytest.skip("ffmpeg is not installed or available in PATH")
        
    output_image = tmp_path / "screenshot.png"
    
    # 2. スクリーンショットの抽出 (scale="1280:-1")
    result = extract_screenshot(
        video_path=str(input_video),
        timestamp=1.0,
        output_path=str(output_image),
        scale="1280:-1"
    )
    
    assert result == str(output_image)
    assert output_image.exists()
    
    # 3. ファイルサイズ、解像度、アスペクト比の検証
    file_size = output_image.stat().st_size
    assert file_size > 0  # 空ファイルではない
    
    with Image.open(output_image) as img:
        width, height = img.size
        # 幅は 1280 になっているはず
        assert width == 1280
        # 元が 1920x1080 (16:9) で、幅が 1280 の場合、高さは 720 になるはず
        assert height == 720
        # アスペクト比の検証 (16/9)
        assert pytest.approx(width / height, rel=1e-2) == 16 / 9


def test_extract_screenshot_out_of_bounds_timestamp(tmp_path):
    """
    指定されたタイムスタンプが動画のデュレーション範囲外の場合に
    ValueError が送出されることを検証します。
    """
    # 1. テスト用動画ファイルを生成
    input_video = tmp_path / "testsrc.mp4"
    create_cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=640x360:rate=24",
        "-c:v", "libx264",
        "-y",
        str(input_video)
    ]
    try:
        subprocess.run(create_cmd, check=True, capture_output=True, timeout=30.0)
    except FileNotFoundError:
        pytest.skip("ffmpeg is not installed")
        
    output_image = tmp_path / "screenshot.png"
    
    # デュレーションは 2.0 秒なので、3.0 秒は範囲外
    with pytest.raises(ValueError, match="is out of video duration"):
        extract_screenshot(str(input_video), 3.0, str(output_image))
        
    # マイナスのタイムスタンプも範囲外
    with pytest.raises(ValueError, match="is out of video duration"):
        extract_screenshot(str(input_video), -0.5, str(output_image))


def test_extract_screenshot_jpeg_quality(tmp_path):
    """
    出力ファイルの拡張子が .jpg または .jpeg の場合に
    -q:v 2 オプションが FFmpeg コマンドに正しく追加されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 3.0
    output_path = str(tmp_path / "output_frame.jpg")
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        result = extract_screenshot(video_path, timestamp, output_path)
        
        assert result == output_path
        
        # 期待される FFmpeg コマンドに "-q:v", "2" が含まれているか確認
        expected_cmd = [
            "ffmpeg",
            "-ss", "3.0",
            "-i", video_path,
            "-vframes", "1",
            "-vf", "scale=1280:-1:flags=lanczos",
            "-pix_fmt", "rgb24",
            "-q:v", "2",
            "-y",
            output_path
        ]
        mock_run.assert_called_once_with(expected_cmd, check=True, capture_output=True, timeout=30.0)


def test_get_video_duration_exceptions(tmp_path):
    """
    _get_video_duration 内で ffprobe が例外（CalledProcessError, FileNotFoundError, OSError, ValueError）
    をスローした場合に、適切にキャッチして None を返すことを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)

    # 1. subprocess.run が CalledProcessError を投げる場合
    def mock_run_called_process_error(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffprobe", stderr="error")

    with patch("subprocess.run", new=mock_run_called_process_error):
        duration = _get_video_duration(video_path)
        assert duration is None

    # 2. subprocess.run が FileNotFoundError を投げる場合
    def mock_run_file_not_found(*args, **kwargs):
        raise FileNotFoundError("ffprobe not found")

    with patch("subprocess.run", new=mock_run_file_not_found):
        duration = _get_video_duration(video_path)
        assert duration is None

    # 3. subprocess.run が OSError を投げる場合
    def mock_run_os_error(*args, **kwargs):
        raise OSError("Permission denied")

    with patch("subprocess.run", new=mock_run_os_error):
        duration = _get_video_duration(video_path)
        assert duration is None

    # 4. stdout が float に変換できない（ValueError）場合
    class DummyCompletedProcess:
        def __init__(self):
            self.stdout = "not_a_float"
            self.returncode = 0

    def mock_run_invalid_stdout(*args, **kwargs):
        return DummyCompletedProcess()

    with patch("subprocess.run", new=mock_run_invalid_stdout):
        duration = _get_video_duration(video_path)
        assert duration is None


def test_extract_screenshot_output_file_not_created(tmp_path):
    """
    モック環境ではないと判定された状態で、FFmpeg が終了したにも関わらず
    出力ファイルが生成されなかった場合に RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 1.0
    output_path = str(tmp_path / "non_existent_output.png")

    class CustomCallable:
        def __call__(self, cmd, *args, **kwargs):
            if cmd[0] == "ffprobe":
                class DummyCompletedProcess:
                    def __init__(self):
                        self.stdout = "10.0"
                        self.returncode = 0
                return DummyCompletedProcess()
            return None

    custom_runner = CustomCallable()

    with patch("subprocess.run", custom_runner):
        with pytest.raises(RuntimeError, match="Screenshot output file was not created"):
            extract_screenshot(video_path, timestamp, output_path)


def test_extract_screenshot_output_file_empty(tmp_path):
    """
    モック環境ではないと判定された状態で、FFmpeg が終了した際に出力ファイルが
    0バイト（空）だった場合に RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    timestamp = 1.0
    output_path = str(tmp_path / "empty_output.png")

    class CustomCallable:
        def __call__(self, cmd, *args, **kwargs):
            if cmd[0] == "ffprobe":
                class DummyCompletedProcess:
                    def __init__(self):
                        self.stdout = "10.0"
                        self.returncode = 0
                return DummyCompletedProcess()
            Path(output_path).touch()
            return None

    custom_runner = CustomCallable()

    with patch("subprocess.run", custom_runner):
        with pytest.raises(RuntimeError, match="Created screenshot file is empty"):
            extract_screenshot(video_path, timestamp, output_path)


def test_extract_screenshot_os_error(tmp_path):
    """
    subprocess.run が OSError をスローした場合に RuntimeError にラップされて送出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("subprocess.run", side_effect=OSError("Permission denied")):
        with pytest.raises(RuntimeError, match="FFmpeg execution failed due to OS error"):
            extract_screenshot(video_path, 5.0, output_path)


def test_extract_screenshot_negative_timestamp_no_duration(tmp_path):
    """
    duration が取得できない場合でも、負数のタイムスタンプは ValueError になることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("backend.screenshot_generator._get_video_duration", return_value=None):
        with pytest.raises(ValueError, match="is out of video duration"):
            extract_screenshot(video_path, -1.0, output_path)


def test_get_video_duration_unexpected_exception(tmp_path):
    """
    _get_video_duration 内で予期せぬ例外が発生した際、
    TechnicalDebtStore.register_debt が呼び出されることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)

    # _get_video_duration の is_mocked 判定を回避するため、通常の関数を side_effect でパッチします
    def mock_run_func(*args, **kwargs):
        raise Exception("Unexpected crash")
        
    with patch("backend.screenshot_generator.subprocess.run", new=mock_run_func), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        duration = _get_video_duration(video_path)
        assert duration is None
        mock_register.assert_called_once()


def test_extract_screenshot_unexpected_exception(tmp_path):
    """
    extract_screenshot 内で予期せぬ例外が発生した際、
    TechnicalDebtStore.register_debt が呼び出され、かつ RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("backend.screenshot_generator.subprocess.run", side_effect=Exception("Unexpected ffmpeg crash")), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        with pytest.raises(RuntimeError, match="Unexpected error in extract_screenshot"):
            extract_screenshot(video_path, 1.0, output_path)
        mock_register.assert_called_once()


def test_generate_multiple_screenshots_unexpected_exception(tmp_path):
    """
    generate_multiple_screenshots 内で予期せぬ例外が発生した際、
    TechnicalDebtStore.register_debt が呼び出され、かつ RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_dir = str(tmp_path / "screenshots")

    # Path.mkdir で予期せぬ例外を発生させる
    with patch("pathlib.Path.mkdir", side_effect=Exception("Unexpected directory creation error")), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt") as mock_register:
        with pytest.raises(RuntimeError, match="Unexpected error in generate_multiple_screenshots"):
            generate_multiple_screenshots(video_path, [1.0, 2.0], output_dir)
        mock_register.assert_called_once()




def test_extract_screenshot_failed_message(tmp_path):
    """
    extract_screenshot 内で予期せぬ例外が発生した際、
    発生する RuntimeError のメッセージに 'Screenshot generation failed' が含まれることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("backend.screenshot_generator.subprocess.run", side_effect=Exception("Unexpected ffmpeg crash")),          patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt"):
        with pytest.raises(RuntimeError) as exc_info:
            extract_screenshot(video_path, 1.0, output_path)
        assert "Screenshot generation failed" in str(exc_info.value)


def test_generate_multiple_screenshots_failed_message(tmp_path):
    """
    generate_multiple_screenshots 内で予期せぬ例外が発生した際、
    発生する RuntimeError のメッセージに 'Screenshot generation failed' が含まれることを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_dir = str(tmp_path / "screenshots")

    with patch("pathlib.Path.mkdir", side_effect=Exception("Unexpected directory creation error")), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore.register_debt"):
        with pytest.raises(RuntimeError) as exc_info:
            generate_multiple_screenshots(video_path, [1.0, 2.0], output_dir)
        assert "Screenshot generation failed" in str(exc_info.value)


def test_get_video_duration_tde_exception(tmp_path):
    """
    _get_video_duration 内で予期せぬ例外が発生し、かつ TechnicalDebtStore での登録も
    例外 (tde) になった場合に、正しく logging.error が呼ばれ、最終的に None を返すことを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)

    def mock_run_func(*args, **kwargs):
        raise Exception("Unexpected crash")
        
    with patch("backend.screenshot_generator.subprocess.run", new=mock_run_func), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_store_class:
        
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = Exception("TechnicalDebtStore error")
        mock_store_class.return_value = mock_store
        
        with patch("backend.screenshot_generator.logger.error") as mock_logger_error:
            duration = _get_video_duration(video_path)
            assert duration is None
            assert mock_logger_error.call_count >= 2
            any_tde_log = any("Failed to register technical debt" in call[0][0] for call in mock_logger_error.call_args_list)
            assert any_tde_log


def test_extract_screenshot_tde_exception(tmp_path):
    """
    extract_screenshot 内で予期せぬ例外が発生し、かつ TechnicalDebtStore での登録も
    例外 (tde) になった場合に、正しく logging.error が呼ばれ、最終的に RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_path = str(tmp_path / "out.png")

    with patch("backend.screenshot_generator.subprocess.run", side_effect=Exception("Unexpected ffmpeg crash")), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_store_class:
        
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = Exception("TechnicalDebtStore error")
        mock_store_class.return_value = mock_store
        
        with patch("backend.screenshot_generator.logger.error") as mock_logger_error:
            with pytest.raises(RuntimeError, match="Screenshot generation failed"):
                extract_screenshot(video_path, 1.0, output_path)
            
            any_tde_log = any("Failed to register technical debt in extract_screenshot" in call[0][0] for call in mock_logger_error.call_args_list)
            assert any_tde_log


def test_generate_multiple_screenshots_tde_exception(tmp_path):
    """
    generate_multiple_screenshots 内で予期せぬ例外が発生し、かつ TechnicalDebtStore での登録も
    例外 (tde) になった場合に、正しく logging.error が呼ばれ、最終的に RuntimeError が発生することを検証します。
    """
    video_file = tmp_path / "test_video.mp4"
    video_file.touch()
    video_path = str(video_file)
    output_dir = str(tmp_path / "screenshots")

    with patch("pathlib.Path.mkdir", side_effect=Exception("Unexpected directory creation error")), \
         patch("backend.agents.memory.technical_debt.TechnicalDebtStore") as mock_store_class:
        
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = Exception("TechnicalDebtStore error")
        mock_store_class.return_value = mock_store
        
        with patch("backend.screenshot_generator.logger.error") as mock_logger_error:
            with pytest.raises(RuntimeError, match="Screenshot generation failed"):
                generate_multiple_screenshots(video_path, [1.0, 2.0], output_dir)
            
            any_tde_log = any("Failed to register technical debt in generate_multiple_screenshots" in call[0][0] for call in mock_logger_error.call_args_list)
            assert any_tde_log

