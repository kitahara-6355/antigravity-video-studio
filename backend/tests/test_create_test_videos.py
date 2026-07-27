import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

import backend.scripts.create_test_videos as ctv

@pytest.fixture
def setup_dirs(tmp_path):
    """Set up temporary directories for testing and override module globals."""
    vault_raw = tmp_path / "vault-assets" / "raw"
    test_videos_dir = tmp_path / "vault-assets" / "test_videos"
    vault_raw.mkdir(parents=True, exist_ok=True)
    test_videos_dir.mkdir(parents=True, exist_ok=True)
    
    # Save original globals
    old_raw = ctv.VAULT_RAW
    old_test = ctv.TEST_VIDEOS_DIR
    old_backend = ctv.BACKEND_DIR
    
    # Apply mocks
    ctv.VAULT_RAW = vault_raw
    ctv.TEST_VIDEOS_DIR = test_videos_dir
    ctv.BACKEND_DIR = tmp_path
    
    yield tmp_path, vault_raw, test_videos_dir
    
    # Restore original globals
    ctv.VAULT_RAW = old_raw
    ctv.TEST_VIDEOS_DIR = old_test
    ctv.BACKEND_DIR = old_backend


def test_find_source_video_in_raw(setup_dirs):
    """Test find_source_video when a video exists in vault-assets/raw."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_video = vault_raw / "video.mp4"
    dummy_video.write_bytes(b"dummy")
    
    found = ctv.find_source_video()
    assert found == dummy_video


def test_find_source_video_in_backend(setup_dirs):
    """Test find_source_video when raw is empty but a video exists in backend."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    # Put video in backend folder but not test_videos/node_modules
    custom_dir = tmp_path / "custom_module"
    custom_dir.mkdir()
    dummy_video = custom_dir / "video.mkv"
    dummy_video.write_bytes(b"dummy")
    
    # Also put one in test_videos and node_modules to verify they are ignored
    ignored_video_1 = test_videos_dir / "ignored.mp4"
    ignored_video_1.touch()
    
    node_modules_dir = tmp_path / "node_modules"
    node_modules_dir.mkdir()
    ignored_video_2 = node_modules_dir / "ignored.mp4"
    ignored_video_2.touch()
    
    found = ctv.find_source_video()
    assert found == dummy_video


def test_find_source_video_not_found(setup_dirs):
    """Test find_source_video when no video matches search criteria."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    found = ctv.find_source_video()
    assert found is None


def test_run_ffmpeg_success():
    """Test run_ffmpeg returns True when ffmpeg command succeeds."""
    with patch("backend.scripts.create_test_videos.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run success")
        assert result is True
        mock_run.assert_called_once()


def test_run_ffmpeg_failure():
    """Test run_ffmpeg returns False when ffmpeg command fails."""
    with patch("backend.scripts.create_test_videos.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Error details")
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run failure")
        assert result is False
        mock_run.assert_called_once()


def test_generate_synthetic_source_success(setup_dirs):
    """Test generate_synthetic_source returns synthetic path on success."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("backend.scripts.create_test_videos.run_ffmpeg") as mock_run_ffmpeg:
        mock_run_ffmpeg.return_value = True
        result = ctv.generate_synthetic_source()
        assert result == test_videos_dir / "_synthetic_source.mp4"


def test_generate_synthetic_source_failure(setup_dirs):
    """Test generate_synthetic_source returns None on failure."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("backend.scripts.create_test_videos.run_ffmpeg") as mock_run_ffmpeg:
        mock_run_ffmpeg.return_value = False
        result = ctv.generate_synthetic_source()
        assert result is None


def test_create_test_videos(setup_dirs):
    """Test create_test_videos triggers ffmpeg runs and returns dictionary results."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    source = vault_raw / "dummy.mp4"
    source.touch()
    
    with patch("backend.scripts.create_test_videos.run_ffmpeg") as mock_run_ffmpeg:
        mock_run_ffmpeg.return_value = True
        results = ctv.create_test_videos(source)
        assert len(results) == 5
        assert results["test_30sec"] is True
        assert results["test_5min"] is True
        assert results["test_silence"] is True
        assert results["test_mono"] is True
        assert results["test_lowres"] is True
        assert mock_run_ffmpeg.call_count == 5


def test_main_success_with_raw(setup_dirs):
    """Test main success scenario where raw video is found and all creations succeed."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_source = vault_raw / "source.mp4"
    dummy_source.touch()
    
    # Mocking create_test_videos returns
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    # Touch output files so stats block in main doesn't fail
    for key in results:
        (test_videos_dir / f"{key}.mp4").touch()
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0


def test_main_fallback_to_synthetic_success(setup_dirs):
    """Test main fallback scenario where raw is missing, synthetic generation succeeds, and creation succeeds."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_synthetic = test_videos_dir / "_synthetic_source.mp4"
    dummy_synthetic.touch()
    
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    # Touch output files
    for key in results:
        (test_videos_dir / f"{key}.mp4").touch()
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None),          patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=dummy_synthetic),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0


def test_main_synthetic_generation_fails(setup_dirs):
    """Test main exits with error code 1 if no source video and synthetic video creation fails."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None),          patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=None):
        with pytest.raises(SystemExit) as excinfo:
            ctv.main()
        assert excinfo.value.code == 1


def test_main_creation_partial_failures(setup_dirs):
    """Test main exits with error code 1 if video generation has partial failures."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_source = vault_raw / "source.mp4"
    dummy_source.touch()
    
    results = {
        "test_30sec": True,
        "test_5min": False,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    # Touch output files for successful ones
    for key, ok in results.items():
        if ok:
            (test_videos_dir / f"{key}.mp4").touch()
            
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 1


def test_main_execution_as_script(setup_dirs):
    """Test script execution behavior when run as __main__ using compile/exec with global subprocess.run mock to cover the entry point."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    # Define a side effect for mock_sub_run to touch the output file (the last argument of the cmd)
    def side_effect(cmd, *args, **kwargs):
        if cmd and len(cmd) > 0:
            out_file = Path(cmd[-1])
            try:
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.touch()
            except Exception:
                pass
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run, \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
         
        # Prepare execution environment
        mod_globals = ctv.__dict__.copy()
        mod_globals["__name__"] = "__main__"
        
        # Read and compile script source
        with open(ctv.__file__, "r", encoding="utf-8") as f:
            code_str = f.read()
            
        # Replace the BACKEND_DIR assignment so it points to our temp directory
        escaped_tmp_path = str(tmp_path).replace("\\", "\\\\")
        code_str = code_str.replace(
            "BACKEND_DIR = Path(__file__).parent",
            f"BACKEND_DIR = Path(r'{escaped_tmp_path}')"
        )
            
        code_obj = compile(code_str, ctv.__file__, "exec")
        
        # The main code will run, try to find or generate source,
        # then run create_test_videos. Everything will succeed via mocked subprocess.run.
        # It should exit with 0.
        with pytest.raises(SystemExit):
            exec(code_obj, mod_globals)
            
        mock_exit.assert_called_once_with(0)


def test_main_execution_as_script_with_raw(setup_dirs):
    """Test script execution behavior when a raw source video exists and is used directly."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    # Create dummy raw video so that find_source_video succeeds
    dummy_raw = vault_raw / "raw_source.mp4"
    dummy_raw.touch()
    
    # Define a side effect for mock_sub_run to touch the output file (the last argument of the cmd)
    def side_effect(cmd, *args, **kwargs):
        if cmd and len(cmd) > 0:
            out_file = Path(cmd[-1])
            try:
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.touch()
            except Exception:
                pass
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run, \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
         
        # Prepare execution environment
        mod_globals = ctv.__dict__.copy()
        mod_globals["__name__"] = "__main__"
        
        # Read and compile script source
        with open(ctv.__file__, "r", encoding="utf-8") as f:
            code_str = f.read()
            
        # Replace the BACKEND_DIR assignment so it points to our temp directory
        escaped_tmp_path = str(tmp_path).replace("\\", "\\\\")
        code_str = code_str.replace(
            "BACKEND_DIR = Path(__file__).parent",
            f"BACKEND_DIR = Path(r'{escaped_tmp_path}')"
        )
            
        code_obj = compile(code_str, ctv.__file__, "exec")
        
        # The main code will run, try to find or generate source,
        # then run create_test_videos. Everything will succeed via mocked subprocess.run.
        # It should exit with 0.
        with pytest.raises(SystemExit):
            exec(code_obj, mod_globals)
            
        mock_exit.assert_called_once_with(0)


def test_run_ffmpeg_filenotfound():
    """Test run_ffmpeg returns False and prints error when FileNotFoundError is raised."""
    with patch("backend.scripts.create_test_videos.subprocess.run", side_effect=FileNotFoundError):
        result = ctv.run_ffmpeg(["-i", "dummy"], "test file not found")
        assert result is False


def test_run_ffmpeg_oserror():
    """Test run_ffmpeg returns False and prints error when OSError is raised."""
    with patch("backend.scripts.create_test_videos.subprocess.run", side_effect=OSError("Disk full")):
        result = ctv.run_ffmpeg(["-i", "dummy"], "test os error")
        assert result is False
