import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import subprocess

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
    dummy_video.write_bytes(b"dummy video content")
    
    found = ctv.find_source_video()
    assert found == dummy_video


def test_find_source_video_in_backend(setup_dirs):
    """Test find_source_video when raw is empty but a video exists in backend."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    # Put video in backend folder but not test_videos/node_modules
    custom_dir = tmp_path / "custom_module"
    custom_dir.mkdir()
    dummy_video = custom_dir / "video.mkv"
    dummy_video.write_bytes(b"dummy video content")
    
    # Also put one in test_videos and node_modules to verify they are ignored
    ignored_video_1 = test_videos_dir / "ignored.mp4"
    ignored_video_1.write_bytes(b"ignored")
    
    node_modules_dir = tmp_path / "node_modules"
    node_modules_dir.mkdir()
    ignored_video_2 = node_modules_dir / "ignored.mp4"
    ignored_video_2.write_bytes(b"ignored")
    
    found = ctv.find_source_video()
    assert found == dummy_video


def test_find_source_video_not_found(setup_dirs):
    """Test find_source_video when no video matches search criteria."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    found = ctv.find_source_video()
    assert found is None


def test_find_source_video_glob_error(setup_dirs):
    """Test find_source_video when glob throws OSError."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch.object(Path, "glob", side_effect=OSError("glob error")):
        found = ctv.find_source_video()
        assert found is None


def test_find_source_video_stat_error(setup_dirs):
    """Test find_source_video when stat throws OSError."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_video = vault_raw / "video.mp4"
    dummy_video.write_bytes(b"dummy")
    
    orig_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if self.name == "video.mp4":
            raise OSError("stat error")
        return orig_stat(self, *args, **kwargs)
        
    with patch.object(Path, "stat", mock_stat):
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


def test_run_ffmpeg_filenotfound():
    """Test run_ffmpeg returns False when ffmpeg command is not found."""
    with patch("backend.scripts.create_test_videos.subprocess.run", side_effect=FileNotFoundError):
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run not found")
        assert result is False


def test_run_ffmpeg_subprocesserror():
    """Test run_ffmpeg returns False when subprocess throws SubprocessError."""
    with patch("backend.scripts.create_test_videos.subprocess.run", side_effect=subprocess.SubprocessError("subprocess error")):
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run subprocess error")
        assert result is False


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


def test_generate_synthetic_source_mkdir_error(setup_dirs):
    """Test generate_synthetic_source returns None when mkdir fails."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch.object(Path, "mkdir", side_effect=OSError("mkdir error")):
        result = ctv.generate_synthetic_source()
        assert result is None


def test_create_test_videos(setup_dirs):
    """Test create_test_videos triggers ffmpeg runs and returns dictionary results."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    source = vault_raw / "dummy.mp4"
    source.write_bytes(b"dummy")
    
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


def test_create_test_videos_invalid_source(setup_dirs):
    """Test create_test_videos returns empty dict when source does not exist."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    source = vault_raw / "nonexistent.mp4"
    results = ctv.create_test_videos(source)
    assert results == {}


def test_create_test_videos_mkdir_error(setup_dirs):
    """Test create_test_videos returns empty dict when mkdir fails."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    source = vault_raw / "dummy.mp4"
    source.write_bytes(b"dummy")
    with patch.object(Path, "mkdir", side_effect=OSError("mkdir error")):
        results = ctv.create_test_videos(source)
        assert results == {}


def test_main_success_with_raw(setup_dirs):
    """Test main success scenario where raw video is found and all creations succeed."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_source = vault_raw / "source.mp4"
    dummy_source.write_bytes(b"dummy source")
    
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
        (test_videos_dir / f"{key}.mp4").write_bytes(b"dummy content")
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source), \
         patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0


def test_main_source_stat_error(setup_dirs):
    """Test main handles stat error on source video gracefully."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_source = vault_raw / "source.mp4"
    dummy_source.write_bytes(b"dummy")
    
    orig_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        if self.name == "source.mp4":
            raise OSError("stat error on source")
        return orig_stat(self, *args, **kwargs)
        
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    for key in results:
        (test_videos_dir / f"{key}.mp4").write_bytes(b"dummy content")
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source), \
         patch("backend.scripts.create_test_videos.create_test_videos", return_value=results), \
         patch.object(Path, "stat", mock_stat):
        res = ctv.main()
        assert res == 0


def test_main_summary_stat_error(setup_dirs):
    """Test main handles stat error on output files gracefully."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_source = vault_raw / "source.mp4"
    dummy_source.write_bytes(b"dummy")
    
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    for key in results:
        (test_videos_dir / f"{key}.mp4").write_bytes(b"dummy content")
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source), \
         patch("backend.scripts.create_test_videos.create_test_videos", return_value=results), \
         patch.object(Path, "stat", side_effect=OSError("stat error on output")):
        res = ctv.main()
        assert res == 0


def test_main_fallback_to_synthetic_success(setup_dirs):
    """Test main fallback scenario where raw is missing, synthetic generation succeeds, and creation succeeds."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_synthetic = test_videos_dir / "_synthetic_source.mp4"
    dummy_synthetic.write_bytes(b"dummy synthetic")
    
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    
    # Touch output files
    for key in results:
        (test_videos_dir / f"{key}.mp4").write_bytes(b"dummy content")
        
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None), \
         patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=dummy_synthetic), \
         patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0


def test_main_synthetic_generation_fails(setup_dirs):
    """Test main exits with error code 1 if no source video and synthetic video creation fails."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None), \
         patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=None):
        with pytest.raises(SystemExit) as excinfo:
            ctv.main()
        assert excinfo.value.code == 1


def test_main_creation_partial_failures(setup_dirs):
    """Test main exits with error code 1 if video generation has partial failures."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_source = vault_raw / "source.mp4"
    dummy_source.write_bytes(b"dummy source")
    
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
            (test_videos_dir / f"{key}.mp4").write_bytes(b"dummy content")
            
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source), \
         patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 1


def test_main_execution_as_script(setup_dirs):
    """Test script execution behavior when run as __main__ using compile/exec with global subprocess.run mock to cover the entry point."""
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    
    dummy_source = vault_raw / "video.mp4"
    dummy_source.write_bytes(b"dummy")
    
    with patch("subprocess.run") as mock_sub_run, \
         patch("sys.exit", side_effect=SystemExit) as mock_exit:
         
        # Mock subprocess.run to return exit code 0 to simulate successful ffmpeg runs
        mock_sub_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        # Prepare execution environment
        mod_globals = ctv.__dict__.copy()
        mod_globals["__name__"] = "__main__"
        mod_globals["__file__"] = str(tmp_path / "create_test_videos.py")
        
        # Read and compile script source
        with open(ctv.__file__, "r", encoding="utf-8") as f:
            code_str = f.read()
            
        code_obj = compile(code_str, ctv.__file__, "exec")
        
        with pytest.raises(SystemExit):
            exec(code_obj, mod_globals)
            
        mock_exit.assert_called_once_with(0)
