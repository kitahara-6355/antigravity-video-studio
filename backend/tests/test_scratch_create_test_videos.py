import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

import backend.scripts.create_test_videos as ctv

@pytest.fixture
def setup_dirs(tmp_path):
    vault_raw = tmp_path / "vault-assets" / "raw"
    test_videos_dir = tmp_path / "vault-assets" / "test_videos"
    vault_raw.mkdir(parents=True, exist_ok=True)
    test_videos_dir.mkdir(parents=True, exist_ok=True)
    
    old_raw = ctv.VAULT_RAW
    old_test = ctv.TEST_VIDEOS_DIR
    old_backend = ctv.BACKEND_DIR
    
    ctv.VAULT_RAW = vault_raw
    ctv.TEST_VIDEOS_DIR = test_videos_dir
    ctv.BACKEND_DIR = tmp_path
    
    yield tmp_path, vault_raw, test_videos_dir
    
    ctv.VAULT_RAW = old_raw
    ctv.TEST_VIDEOS_DIR = old_test
    ctv.BACKEND_DIR = old_backend

def test_find_source_video_in_raw(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_video = vault_raw / "video.mp4"
    dummy_video.touch()
    found = ctv.find_source_video()
    assert found == dummy_video

def test_find_source_video_in_backend(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    custom_dir = tmp_path / "custom_module"
    custom_dir.mkdir()
    dummy_video = custom_dir / "video.mkv"
    dummy_video.touch()
    
    ignored_video_1 = test_videos_dir / "ignored.mp4"
    ignored_video_1.touch()
    
    node_modules_dir = tmp_path / "node_modules"
    node_modules_dir.mkdir()
    ignored_video_2 = node_modules_dir / "ignored.mp4"
    ignored_video_2.touch()
    
    found = ctv.find_source_video()
    assert found == dummy_video

def test_find_source_video_not_found(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    found = ctv.find_source_video()
    assert found is None

def test_run_ffmpeg_success():
    with patch("backend.scripts.create_test_videos.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run success")
        assert result is True
        mock_run.assert_called_once()

def test_run_ffmpeg_failure():
    with patch("backend.scripts.create_test_videos.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Error details")
        result = ctv.run_ffmpeg(["-i", "dummy"], "test run failure")
        assert result is False
        mock_run.assert_called_once()

def test_generate_synthetic_source_success(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("backend.scripts.create_test_videos.run_ffmpeg") as mock_run_ffmpeg:
        mock_run_ffmpeg.return_value = True
        result = ctv.generate_synthetic_source()
        assert result == test_videos_dir / "_synthetic_source.mp4"

def test_generate_synthetic_source_failure(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("backend.scripts.create_test_videos.run_ffmpeg") as mock_run_ffmpeg:
        mock_run_ffmpeg.return_value = False
        result = ctv.generate_synthetic_source()
        assert result is None

def test_create_test_videos(setup_dirs):
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
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    dummy_source = vault_raw / "source.mp4"
    dummy_source.touch()
    results = {
        "test_30sec": True,
        "test_5min": True,
        "test_silence": True,
        "test_mono": True,
        "test_lowres": True
    }
    for key in results:
        (test_videos_dir / f"{key}.mp4").touch()
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0

def test_main_fallback_to_synthetic_success(setup_dirs):
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
    for key in results:
        (test_videos_dir / f"{key}.mp4").touch()
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None),          patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=dummy_synthetic),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 0

def test_main_synthetic_generation_fails(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=None),          patch("backend.scripts.create_test_videos.generate_synthetic_source", return_value=None):
        with pytest.raises(SystemExit) as excinfo:
            ctv.main()
        assert excinfo.value.code == 1

def test_main_creation_partial_failures(setup_dirs):
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
    for key, ok in results.items():
        if ok:
            (test_videos_dir / f"{key}.mp4").touch()
    with patch("backend.scripts.create_test_videos.find_source_video", return_value=dummy_source),          patch("backend.scripts.create_test_videos.create_test_videos", return_value=results):
        res = ctv.main()
        assert res == 1

def test_main_execution_as_script(setup_dirs):
    tmp_path, vault_raw, test_videos_dir = setup_dirs
    with patch("subprocess.run") as mock_sub_run,          patch("sys.exit", side_effect=SystemExit) as mock_exit:
        mock_sub_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mod_globals = ctv.__dict__.copy()
        mod_globals["__name__"] = "__main__"
        with open(ctv.__file__, "r", encoding="utf-8") as f:
            code_str = f.read()
        code_obj = compile(code_str, ctv.__file__, "exec")
        with pytest.raises(SystemExit):
            exec(code_obj, mod_globals)
        mock_exit.assert_called_once_with(0)
