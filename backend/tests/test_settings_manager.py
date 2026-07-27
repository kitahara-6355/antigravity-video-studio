import os
import json
import shutil
import sys
import importlib
import pytest
from unittest.mock import MagicMock, patch

# Test targets
import settings_manager
from settings_manager import SettingsManager

@pytest.fixture
def temp_workspace(tmp_path):
    """
    Fixture to isolate testing of SettingsManager from the real file system
    and real constitution/branding state.
    """
    orig_base_dir = settings_manager.BASE_DIR
    orig_video_src_path = settings_manager.VIDEO_SRC_PATH
    
    # Redirect variables to tmp_path
    test_base_dir = str(tmp_path)
    test_video_src_path = os.path.join(test_base_dir, "src", "sample_raw.mp4")
    
    settings_manager.BASE_DIR = test_base_dir
    settings_manager.VIDEO_SRC_PATH = test_video_src_path
    
    # Backup original branding_manager attributes
    orig_constitution = settings_manager.branding_manager.constitution
    orig_user_model = settings_manager.branding_manager.user_model
    orig_save_json = settings_manager.branding_manager._save_json
    
    mock_constitution = {
        "channel_name": "Test Channel",
        "target_audience": "Developers",
        "video_source_name": "original.mp4"
    }
    mock_user_model = {
        "persona": "Tech Blogger"
    }
    
    settings_manager.branding_manager.constitution = mock_constitution
    settings_manager.branding_manager.user_model = mock_user_model
    settings_manager.branding_manager._save_json = MagicMock()
    
    yield tmp_path, mock_constitution, mock_user_model
    
    # Restore original state
    settings_manager.BASE_DIR = orig_base_dir
    settings_manager.VIDEO_SRC_PATH = orig_video_src_path
    settings_manager.branding_manager.constitution = orig_constitution
    settings_manager.branding_manager.user_model = orig_user_model
    settings_manager.branding_manager._save_json = orig_save_json


def test_get_all_settings(temp_workspace):
    """Verify get_all_settings returns correct configuration, including the video existence state."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Video not exists
    res = mgr.get_all_settings()
    assert res["constitution"] == const
    assert res["user_model"] == model
    assert res["video_exists"] is False
    
    # Video exists
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("dummy video data")
        
    res = mgr.get_all_settings()
    assert res["video_exists"] is True


def test_get_video_source(temp_workspace):
    """Verify get_video_source returns correct VIDEO_SRC_PATH."""
    mgr = SettingsManager()
    assert mgr.get_video_source() == settings_manager.VIDEO_SRC_PATH


def test_update_video_source_success(temp_workspace):
    """Verify update_video_source successfully moves the file and updates constitution."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Pre-create VIDEO_SRC_PATH to trigger the removal branch (Line 42)
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("old video content")
        
    # Create temp source video
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("temp video content", encoding="utf-8")
    
    # Perform update with filename
    res = mgr.update_video_source(str(temp_file), "original_name.mp4")
    
    assert res["status"] == "success"
    assert res["filename"] == "original_name.mp4"
    
    # Confirm it was moved and old file was replaced
    assert os.path.exists(settings_manager.VIDEO_SRC_PATH)
    with open(settings_manager.VIDEO_SRC_PATH, "r", encoding="utf-8") as f:
        assert f.read() == "temp video content"
        
    # Confirm branding_manager was updated and saved
    assert const["video_source_name"] == "original_name.mp4"
    settings_manager.branding_manager._save_json.assert_called_once()


def test_update_video_source_error(temp_workspace):
    """Verify update_video_source error handling (TD-238)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("temp content", encoding="utf-8")
    
    # Force exception during shutil.move
    with patch("shutil.move", side_effect=RuntimeError("Mock move error")):
        res = mgr.update_video_source(str(temp_file))
        assert res["status"] == "error"
        assert "Mock move error" in res["message"]


def test_update_identity(temp_workspace):
    """Verify update_identity updates constitution settings."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    res = mgr.update_identity("New Channel", "New Audience")
    assert res["status"] == "success"
    assert const["channel_name"] == "New Channel"
    assert const["target_audience"] == "New Audience"
    settings_manager.branding_manager._save_json.assert_called_once()


def test_export_soul_passport(temp_workspace):
    """Verify export_soul_passport returns the user model."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    assert mgr.export_soul_passport() == model


def test_reset_workspace_success(temp_workspace):
    """Verify reset_workspace deletes the video, segments file, resets constitution, and updates status."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Place files
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("video content")
        
    segments_path = os.path.join(settings_manager.BASE_DIR, "src", "segments_a_plus_plus.json")
    with open(segments_path, "w", encoding="utf-8") as f:
        f.write("segments content")
        
    status_path = os.path.join(settings_manager.BASE_DIR, "src", "transcription_status.json")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write("status content")
        
    # Perform reset
    res = mgr.reset_workspace()
    assert res["status"] == "success"
    
    # Verify files deleted
    assert not os.path.exists(video_path)
    assert not os.path.exists(segments_path)
    
    # Verify status file was reinitialized
    assert os.path.exists(status_path)
    with open(status_path, "r", encoding="utf-8") as f:
        status_data = json.load(f)
        assert status_data["status"] == "idle"
        
    # Verify constitution reset
    assert const["video_source_name"] == ""
    settings_manager.branding_manager._save_json.assert_called_once()


def test_reset_workspace_permission_error_fallback(temp_workspace):
    """Verify reset_workspace handles PermissionError by renaming the file to trash (fallback path)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Place video
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("video content")
        
    fixed_time = 123456789
    original_remove = os.remove
    
    # Custom remove to raise PermissionError specifically for video path
    def mock_remove(path):
        if path == video_path:
            raise PermissionError("Access denied")
        if os.path.exists(path):
            original_remove(path)
            
    mock_rename = MagicMock()
    
    with patch("os.remove", side_effect=mock_remove), \
         patch("os.rename", mock_rename), \
         patch("time.time", return_value=fixed_time):
         
        res = mgr.reset_workspace()
        assert res["status"] == "success"
        
        # Verify it attempted to rename the locked file to trash path
        expected_trash_path = video_path + f".trash_{fixed_time}"
        mock_rename.assert_any_call(video_path, expected_trash_path)


def test_reset_workspace_error(temp_workspace):
    """Verify reset_workspace error handling when remove and rename both fail (TD-240)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("video content")
        
    def mock_remove(path):
        raise PermissionError("Permission denied")
        
    def mock_rename(src, dst):
        raise RuntimeError("Rename failed")
        
    with patch("os.remove", side_effect=mock_remove), \
         patch("os.rename", side_effect=mock_rename):
         
        res = mgr.reset_workspace()
        assert res["status"] == "error"
        assert "Rename failed" in res["message"]


def test_reset_workspace_status_file_write_error(temp_workspace):
    """Verify reset_workspace handles errors during status file writing gracefully (TD-239)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    status_path = os.path.join(settings_manager.BASE_DIR, "src", "transcription_status.json")
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    
    original_open = open
    
    # Custom open that fails when trying to write to the status file
    def mock_open(file, mode="r", *args, **kwargs):
        if str(file) == str(status_path) and "w" in mode:
            raise IOError("Simulated write error (e.g. disk full)")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", mock_open):
        res = mgr.reset_workspace()
        # Even if writing to transcription_status.json fails, the function should suppress it and return success
        assert res["status"] == "success"


def test_import_fallback():
    """Verify the fallback import behavior when branding_manager is not directly importable (Lines 7-9)."""
    sys_modules_backup = sys.modules.copy()
    
    try:
        # Clear settings_manager and branding_manager from sys.modules
        sys.modules.pop('settings_manager', None)
        sys.modules.pop('branding_manager', None)
        
        # Block importing branding_manager directly
        sys.modules['branding_manager'] = None
        
        # Inject mocked branding.branding_manager in sys.modules to simulate fallback success
        mock_branding_module = MagicMock()
        mock_branding_module.branding_manager = MagicMock()
        mock_branding_module.CONSTITUTION_PATH = "dummy_const_path"
        
        sys.modules['branding'] = MagicMock()
        sys.modules['branding.branding_manager'] = mock_branding_module
        
        # Force reload/import of settings_manager
        importlib.invalidate_caches()
        import settings_manager
        
        # It should have successfully imported from the fallback (branding.branding_manager)
        assert settings_manager.branding_manager is not None
        
    finally:
        # Restore sys.modules
        sys.modules.clear()
        sys.modules.update(sys_modules_backup)


def test_update_video_source_multiple_errors(temp_workspace):
    """Verify update_video_source handles multiple error types (OSError, KeyError, TypeError)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("temp content", encoding="utf-8")
    
    # Test KeyError
    with patch("shutil.move", side_effect=KeyError("Simulated KeyError")):
        res = mgr.update_video_source(str(temp_file))
        assert res["status"] == "error"
        assert "Simulated KeyError" in res["message"]
        
    # Test TypeError
    with patch("shutil.move", side_effect=TypeError("Simulated TypeError")):
        res = mgr.update_video_source(str(temp_file))
        assert res["status"] == "error"
        assert "Simulated TypeError" in res["message"]

    # Test OSError
    with patch("shutil.move", side_effect=OSError("Simulated OSError")):
        res = mgr.update_video_source(str(temp_file))
        assert res["status"] == "error"
        assert "Simulated OSError" in res["message"]


def test_reset_workspace_segments_permission_error_fallback(temp_workspace):
    """Verify reset_workspace handles PermissionError for segments file by renaming to trash."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Place segments file
    segments_path = os.path.join(settings_manager.BASE_DIR, "src", "segments_a_plus_plus.json")
    os.makedirs(os.path.dirname(segments_path), exist_ok=True)
    with open(segments_path, "w", encoding="utf-8") as f:
        f.write("segments content")
        
    fixed_time = 987654321
    original_remove = os.remove
    
    # Custom remove to raise PermissionError specifically for segments path
    def mock_remove(path):
        if path == segments_path:
            raise PermissionError("Access denied")
        if os.path.exists(path):
            original_remove(path)
            
    mock_rename = MagicMock()
    
    with patch("os.remove", side_effect=mock_remove), \
         patch("os.rename", mock_rename), \
         patch("time.time", return_value=fixed_time):
         
        res = mgr.reset_workspace()
        assert res["status"] == "success"
        
        # Verify it attempted to rename the locked segments file to trash path
        expected_trash_path = segments_path + f".trash_{fixed_time}"
        mock_rename.assert_any_call(segments_path, expected_trash_path)


def test_reset_workspace_status_file_type_error(temp_workspace):
    """Verify reset_workspace handles TypeError during status file writing gracefully."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Mock json.dump to raise TypeError
    with patch("json.dump", side_effect=TypeError("Simulated TypeError")):
        res = mgr.reset_workspace()
        assert res["status"] == "success"


def test_update_identity_error(temp_workspace):
    """Verify update_identity error handling when saving fails."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Force Exception in branding_manager._save_json
    settings_manager.branding_manager._save_json.side_effect = OSError("Disk write failed")
    
    res = mgr.update_identity("Err Channel", "Err Audience")
    assert res["status"] == "error"
    assert "Disk write failed" in res["message"]


def test_update_video_source_permission_error_fallback(temp_workspace):
    """Verify update_video_source handles PermissionError on remove by renaming file."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("old video")
        
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("new video content", encoding="utf-8")
    
    fixed_time = 123456789
    original_remove = os.remove
    
    # Custom remove to raise PermissionError specifically for video path
    def mock_remove(path):
        if path == video_path:
            raise PermissionError("Access denied")
        if os.path.exists(path):
            original_remove(path)
            
    mock_rename = MagicMock()
    
    with patch("os.remove", side_effect=mock_remove),          patch("os.rename", mock_rename),          patch("time.time", return_value=fixed_time):
         
        res = mgr.update_video_source(str(temp_file), "new_name.mp4")
        assert res["status"] == "success"
        
        # Verify it renamed the locked file
        expected_trash_path = video_path + f".trash_{fixed_time}"
        mock_rename.assert_any_call(video_path, expected_trash_path)


def test_get_all_settings_none_fallback(temp_workspace):
    """Verify get_all_settings returns empty dictionaries when branding_manager attributes are None."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Force None properties
    settings_manager.branding_manager.constitution = None
    settings_manager.branding_manager.user_model = None
    
    res = mgr.get_all_settings()
    assert res["constitution"] == {}
    assert res["user_model"] == {}


def test_update_video_source_none_constitution_fallback(temp_workspace):
    """Verify update_video_source handles None constitution by initializing it to dict."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    settings_manager.branding_manager.constitution = None
    
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("temp video content", encoding="utf-8")
    
    res = mgr.update_video_source(str(temp_file), "fallback_name.mp4")
    assert res["status"] == "success"
    assert settings_manager.branding_manager.constitution is not None
    assert settings_manager.branding_manager.constitution["video_source_name"] == "fallback_name.mp4"


def test_update_identity_none_constitution_fallback(temp_workspace):
    """Verify update_identity handles None constitution by initializing it to dict."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    settings_manager.branding_manager.constitution = None
    
    res = mgr.update_identity("Fallback Channel", "Fallback Audience")
    assert res["status"] == "success"
    assert settings_manager.branding_manager.constitution is not None
    assert settings_manager.branding_manager.constitution["channel_name"] == "Fallback Channel"
    assert settings_manager.branding_manager.constitution["target_audience"] == "Fallback Audience"


def test_reset_workspace_none_constitution_fallback(temp_workspace):
    """Verify reset_workspace handles None constitution by initializing it to dict."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    settings_manager.branding_manager.constitution = None
    
    res = mgr.reset_workspace()
    assert res["status"] == "success"
    assert settings_manager.branding_manager.constitution is not None
    assert settings_manager.branding_manager.constitution["video_source_name"] == ""


def test_safe_delete_file_other_oserror(temp_workspace):
    """Verify _safe_delete_file raises OSError (not PermissionError) and logs error."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("dummy")
        
    with patch("os.remove", side_effect=OSError("Disk read failure")), \
         patch("settings_manager.logger.error") as mock_log_error:
        with pytest.raises(OSError, match="Disk read failure"):
            mgr._safe_delete_file(video_path)
        mock_log_error.assert_called_once()
        assert "Failed to remove file" in mock_log_error.call_args[0][0]


def test_safe_delete_file_permission_error_and_rename_failure(temp_workspace):
    """Verify _safe_delete_file logs error on rename failure after PermissionError."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    video_path = settings_manager.VIDEO_SRC_PATH
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "w", encoding="utf-8") as f:
        f.write("dummy")
        
    with patch("os.remove", side_effect=PermissionError("Permission denied")), \
         patch("os.rename", side_effect=RuntimeError("Rename failure")), \
         patch("settings_manager.logger.warning") as mock_log_warn, \
         patch("settings_manager.logger.error") as mock_log_error:
        with pytest.raises(RuntimeError, match="Rename failure"):
            mgr._safe_delete_file(video_path)
        mock_log_warn.assert_called_once()
        mock_log_error.assert_called_once()
        assert "Failed to rename locked file" in mock_log_error.call_args[0][0]


def test_update_video_source_broad_exception(temp_workspace):
    """Verify update_video_source logs broad exceptions using logger.error."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    temp_file = tmp_path / "temp_input.mp4"
    temp_file.write_text("temp video content", encoding="utf-8")
    
    # We raise an Exception (not OSError) to trigger the general exception handler
    with patch("shutil.move", side_effect=Exception("Unexpected failure")), \
         patch("settings_manager.logger.error") as mock_log_error:
        res = mgr.update_video_source(str(temp_file))
        assert res["status"] == "error"
        assert "Unexpected failure" in res["message"]
        mock_log_error.assert_called_once()
        assert "Error updating video source" in mock_log_error.call_args[0][0]


def test_update_identity_broad_exception(temp_workspace):
    """Verify update_identity logs broad exceptions using logger.error."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    with patch("settings_manager.branding_manager._save_json", side_effect=Exception("Unexpected DB fail")), \
         patch("settings_manager.logger.error") as mock_log_error:
        res = mgr.update_identity("Channel", "Audience")
        assert res["status"] == "error"
        assert "Unexpected DB fail" in res["message"]
        mock_log_error.assert_called_once()
        assert "Error updating identity" in mock_log_error.call_args[0][0]


def test_reset_workspace_broad_exception(temp_workspace):
    """Verify reset_workspace logs broad exceptions using logger.error."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    with patch("settings_manager.VIDEO_SRC_PATH", new=None), \
         patch("settings_manager.logger.error") as mock_log_error:
        res = mgr.reset_workspace()
        assert res["status"] == "error"
        mock_log_error.assert_called_once()
        assert "Error resetting workspace" in mock_log_error.call_args[0][0]


def test_reset_workspace_status_file_warning(temp_workspace):
    """Verify reset_workspace logs warning if writing the status file fails."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    status_path = os.path.join(settings_manager.BASE_DIR, "src", "transcription_status.json")
    os.makedirs(os.path.dirname(status_path), exist_ok=True)
    
    # Custom open that fails when trying to write to the status file
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if str(file) == str(status_path) and "w" in mode:
            raise TypeError("Simulated TypeError")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", mock_open), \
         patch("settings_manager.logger.warning") as mock_log_warn:
        res = mgr.reset_workspace()
        assert res["status"] == "success"
        mock_log_warn.assert_called_once()
        assert "Failed to write workspace reset status" in mock_log_warn.call_args[0][0]


def test_ensure_constitution_invalid_type(temp_workspace):
    """Verify _ensure_constitution resets the constitution to a dict if it is an invalid type (e.g. list)."""
    tmp_path, const, model = temp_workspace
    mgr = SettingsManager()
    
    # Set to invalid type
    settings_manager.branding_manager.constitution = ["not", "a", "dict"]
    
    res = mgr._ensure_constitution()
    assert isinstance(res, dict)
    assert settings_manager.branding_manager.constitution == {}
