import pytest
import subprocess
import json
import os
import glob
import runpy
from unittest.mock import MagicMock, patch

import inspect_video

@pytest.fixture
def mock_subprocess_run():
    with patch('subprocess.run') as mock_run, \
         patch('os.path.exists', return_value=True):
        yield mock_run

def test_inspect_video_video_and_audio(mock_subprocess_run, capsys):
    # Mock return data containing both video and audio streams
    mock_data = {
        "format": {
            "duration": "123.45",
            "size": str(10 * 1024 * 1024), # 10MB
            "bit_rate": "640000" # 640kbps
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "r_frame_rate": "30/1",
                "nb_frames": "3700"
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 2
            }
        ]
    }
    
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_path.mp4", "Test Label")
    
    assert duration == 123.45
    captured = capsys.readouterr()
    assert "=== Test Label ===" in captured.out
    assert "Duration: 123.5s" in captured.out
    assert "Size: 10.0MB" in captured.out
    assert "Bitrate: 640 kbps" in captured.out
    assert "Video: h264 1920x1080 @ 30/1 fps, frames=3700" in captured.out
    assert "Audio: aac 44100Hz 2ch" in captured.out

def test_inspect_video_video_only(mock_subprocess_run, capsys):
    # Mock data with video stream only
    mock_data = {
        "format": {
            "duration": "50.0",
            "size": str(5 * 1024 * 1024),
            "bit_rate": "800000"
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "codec_name": "vp9",
                "r_frame_rate": "60/1",
                "nb_frames": "3000"
            }
        ]
    }
    
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_video.mp4", "Video Only")
    
    assert duration == 50.0
    captured = capsys.readouterr()
    assert "Video: vp9 1280x720 @ 60/1 fps, frames=3000" in captured.out
    assert "Audio:" not in captured.out

def test_inspect_video_audio_only(mock_subprocess_run, capsys):
    # Mock data with audio stream only
    mock_data = {
        "format": {
            "duration": "600.0",
            "size": str(2 * 1024 * 1024),
            "bit_rate": "128000"
        },
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "48000",
                "channels": 1
            }
        ]
    }
    
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_audio.mp3", "Audio Only")
    
    assert duration == 600.0
    captured = capsys.readouterr()
    assert "Audio: mp3 48000Hz 1ch" in captured.out
    assert "Video:" not in captured.out

def test_inspect_video_missing_fields(mock_subprocess_run, capsys):
    # Mock data with fields missing to verify robust fallback
    mock_data = {
        "format": {},
        "streams": [
            {
                "codec_type": "video"
                # width, height, etc missing
            },
            {
                "codec_type": "audio"
            }
        ]
    }
    
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_faulty.mp4", "Faulty Format")
    
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "Video: ? ?x? @ ? fps, frames=?" in captured.out
    assert "Audio: ? ?Hz ?ch" in captured.out

def test_main_flow_with_raw_dir_existing():
    with patch('inspect_video.inspect_video') as mock_inspect, \
         patch('glob.glob') as mock_glob, \
         patch('os.path.exists') as mock_exists, \
         patch('os.listdir') as mock_listdir:
        
        mock_inspect.return_value = 10.0
        mock_glob.return_value = ['merged_1.mp4', 'merged_2.mp4']
        mock_exists.return_value = True
        mock_listdir.return_value = ['raw1.mp4', 'raw2.mp4', 'not_video.txt']
        
        inspect_video.main()
        
        # Verify inspect_video is called for final, preview, merged and MP4 raw files
        # Final (1) + Preview (1) + Merged (2) + RAW (2) = 6 calls
        assert mock_inspect.call_count == 6
        
        # Verify first argument in calls
        calls = [c[0][0] for c in mock_inspect.call_args_list]
        assert any("final" in c for c in calls)
        assert any("preview" in c for c in calls)
        assert any("merged_1.mp4" in c for c in calls)
        assert any("raw1.mp4" in c for c in calls)
        assert not any("not_video.txt" in c for c in calls)

def test_main_flow_without_raw_dir():
    with patch('inspect_video.inspect_video') as mock_inspect, \
         patch('glob.glob') as mock_glob, \
         patch('os.path.exists') as mock_exists:
        
        mock_inspect.return_value = 10.0
        mock_glob.return_value = []
        mock_exists.return_value = False
        
        inspect_video.main()
        
        # Final (1) + Preview (1) = 2 calls
        assert mock_inspect.call_count == 2

def test_main_flow_with_bug_diagnosis(capsys):
    with patch('inspect_video.inspect_video') as mock_inspect, \
         patch('glob.glob') as mock_glob, \
         patch('os.path.exists') as mock_exists:
        
        # Make the first call (d_final) return > 1800 to trigger the bug print
        mock_inspect.side_effect = [1900.0, 10.0]
        mock_glob.return_value = []
        mock_exists.return_value = False
        
        inspect_video.main()
        
        assert mock_inspect.call_count == 2
        captured = capsys.readouterr()
        assert ">>> BUG CONFIRMED: SmartCut selection NOT applied to render!" in captured.out

def test_script_execution_via_runpy():
    # Mock subprocess.run globally (which is called by inspect_video inside main)
    # Also mock glob.glob and os.path.exists to avoid real filesystem access
    mock_data = {
        "format": {
            "duration": "100.0",
            "size": "10485760",
            "bit_rate": "800000"
        },
        "streams": []
    }
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    
    def exists_side_effect(path):
        path_str = str(path)
        if "raw_videos" in path_str or "merged" in path_str:
            return False
        return True

    with patch('subprocess.run', return_value=mock_result) as mock_run, \
         patch('glob.glob', return_value=[]) as mock_glob, \
         patch('os.path.exists', side_effect=exists_side_effect) as mock_exists:
        
        # Execute the module as __main__
        # This will run the "if __name__ == '__main__': main()" block
        if "66b0c389" in __file__:
            inspect_video_path = os.path.join(os.path.dirname(__file__), "inspect_video.py")
        else:
            inspect_video_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "inspect_video.py")
        runpy.run_path(inspect_video_path, run_name="__main__")
        
        # Verify subprocess.run was called for both final and preview inspection
        assert mock_run.call_count == 2

def test_inspect_video_json_decode_error(mock_subprocess_run):
    mock_result = MagicMock()
    mock_result.stdout = "invalid json data"
    mock_subprocess_run.return_value = mock_result
    
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("dummy_corrupt.mp4", "Corrupt JSON")
    assert "Failed to parse ffprobe output as JSON" in str(exc_info.value)

def test_inspect_video_other_stream_types(mock_subprocess_run, capsys):
    mock_data = {
        "format": {
            "duration": "10.0",
            "size": "1024",
            "bit_rate": "1000"
        },
        "streams": [
            {
                "codec_type": "subtitle",
                "codec_name": "srt"
            }
        ]
    }
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_subtitle.mp4", "Subtitle Only")
    
    assert duration == 10.0
    captured = capsys.readouterr()
    assert "Video:" not in captured.out
    assert "Audio:" not in captured.out


# ============================================================
# inspect_thumbnail Tests
# ============================================================

def test_inspect_thumbnail_success(tmp_path):
    from PIL import Image
    thumb_path = tmp_path / "thumb_ok.png"
    # 1280x720, 16:9
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img.save(thumb_path, "PNG")
    
    result = inspect_video.inspect_thumbnail(thumb_path, "Test Thumbnail OK")
    assert result["path"] == str(thumb_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0

def test_inspect_thumbnail_file_not_found(tmp_path):
    nonexistent = tmp_path / "missing.png"
    with pytest.raises(FileNotFoundError):
        inspect_video.inspect_thumbnail(nonexistent)

def test_inspect_thumbnail_too_large(tmp_path):
    from PIL import Image
    thumb_path = tmp_path / "thumb_large.png"
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img.save(thumb_path, "PNG")
    
    # ファイルサイズチェックをモックする、あるいは stat をモックする
    with patch("pathlib.Path.stat") as mock_stat:
        mock_meta = MagicMock()
        mock_meta.st_size = 4 * 1024 * 1024 + 10 # 4MB + 10 bytes
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError) as exc_info:
            inspect_thumbnail_too_large_block = lambda: inspect_video.inspect_thumbnail(thumb_path)
            pytest.raises(ValueError, inspect_thumbnail_too_large_block)
            inspect_thumbnail_too_large_block()
        assert "exceeds 4MB limit" in str(exc_info.value)

def test_inspect_thumbnail_corrupted(tmp_path):
    thumb_path = tmp_path / "corrupt.png"
    # 不正なデータを書き込む
    thumb_path.write_bytes(b"invalid image data bytes")
    
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_thumbnail(thumb_path)
    assert "corrupted or invalid format" in str(exc_info.value)

def test_inspect_thumbnail_invalid_resolution(tmp_path):
    from PIL import Image
    thumb_path = tmp_path / "thumb_small.png"
    # 解像度不足 (640x360)
    img = Image.new("RGB", (640, 360), color=(100, 100, 100))
    img.save(thumb_path, "PNG")
    
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_thumbnail(thumb_path)
    assert "Resolution must be at least 1280x720" in str(exc_info.value)

def test_inspect_thumbnail_invalid_aspect_ratio(tmp_path):
    from PIL import Image
    thumb_path = tmp_path / "thumb_ratio.png"
    # アスペクト比が 16:9 ではない (1280x800)
    img = Image.new("RGB", (1280, 800), color=(100, 100, 100))
    img.save(thumb_path, "PNG")
    
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_thumbnail(thumb_path)
    assert "Aspect ratio must be 16:9" in str(exc_info.value)


# ============================================================
# New robust error handling tests
# ============================================================

def test_inspect_video_file_not_found():
    with pytest.raises(FileNotFoundError) as exc_info:
        inspect_video.inspect_video("nonexistent_file.mp4", "Nonexistent")
    assert "Video file not found" in str(exc_info.value)

def test_inspect_video_ffprobe_not_found(mock_subprocess_run):
    mock_subprocess_run.side_effect = FileNotFoundError("ffprobe not found")
    with pytest.raises(RuntimeError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", "No ffprobe")
    assert "ffprobe command not found" in str(exc_info.value)

def test_inspect_video_ffprobe_failed(mock_subprocess_run):
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffprobe"],
        stderr="ffprobe error output"
    )
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", "ffprobe Error")
    assert "ffprobe execution failed with exit code 1" in str(exc_info.value)


# ============================================================
# Robust Error Handling & Cast Tests
# ============================================================

def test_inspect_video_invalid_numeric_fields(mock_subprocess_run, capsys):
    mock_data = {
        "format": {
            "duration": "N/A",
            "size": "invalid_size",
            "bit_rate": None
        },
        "streams": []
    }
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(mock_data)
    mock_subprocess_run.return_value = mock_result
    
    duration = inspect_video.inspect_video("dummy_path.mp4", "Test Invalid Numbers")
    
    assert duration == 0.0
    captured = capsys.readouterr()
    assert "Duration: 0.0s" in captured.out
    assert "Size: 0.0MB" in captured.out
    assert "Bitrate: 0 kbps" in captured.out

def test_inspect_video_not_dict_output(mock_subprocess_run):
    # ffprobe output parses to list, not dict
    mock_result = MagicMock()
    mock_result.stdout = json.dumps(["not", "a", "dict"])
    mock_subprocess_run.return_value = mock_result
    
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("dummy_path.mp4", "Not Dict")
    assert "Expected ffprobe output JSON to be a dictionary" in str(exc_info.value)

def test_inspect_thumbnail_zero_dimension(tmp_path):
    from PIL import Image
    thumb_path = tmp_path / "thumb_zero.png"
    thumb_path.touch() # Create dummy file so that exists() check passes
    
    # Mocking Image.open to return image with size (1280, 0)
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.size = (1280, 0)
        # We need to support the context manager structure: with Image.open(...) as img:
        mock_open.return_value.__enter__.return_value = mock_img
        
        with pytest.raises(ValueError) as exc_info:
            inspect_video.inspect_thumbnail(thumb_path)
        assert "Height must be greater than zero" in str(exc_info.value)


def test_inspect_video_parameter_validation():
    # Test invalid path types
    with pytest.raises(TypeError) as exc_info:
        inspect_video.inspect_video(None, "Label")
    assert "path must be a string or path-like object, not None" in str(exc_info.value)

    with pytest.raises(TypeError) as exc_info:
        inspect_video.inspect_video(123, "Label")
    assert "path must be a string or path-like object, got int" in str(exc_info.value)

    # Test empty path
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("", "Label")
    assert "path cannot be empty or whitespace only" in str(exc_info.value)

    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("   ", "Label")
    assert "path cannot be empty or whitespace only" in str(exc_info.value)

    # Test invalid label types
    with pytest.raises(TypeError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", None)
    assert "label must be a string, not None" in str(exc_info.value)

    with pytest.raises(TypeError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", 123)
    assert "label must be a string, got int" in str(exc_info.value)

    # Test empty label
    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", "")
    assert "label cannot be empty or whitespace only" in str(exc_info.value)

    with pytest.raises(ValueError) as exc_info:
        inspect_video.inspect_video("dummy.mp4", "   ")
    assert "label cannot be empty or whitespace only" in str(exc_info.value)
