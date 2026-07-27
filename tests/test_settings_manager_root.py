import os
import sys
import json
import shutil
import pytest
import importlib
from unittest.mock import MagicMock, patch
from pathlib import Path

# backend パス追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import settings_manager
from settings_manager import SettingsManager

@pytest.fixture
def mock_branding_manager():
    # settings_manager.branding_manager を一時的に差し替える
    original_bm = settings_manager.branding_manager
    original_const_path = settings_manager.CONSTITUTION_PATH
    
    mock_bm = MagicMock()
    mock_bm.constitution = {
        "channel_name": "Test Channel",
        "target_audience": "Test Audience",
        "video_source_name": "old_video.mp4"
    }
    mock_bm.user_model = {
        "name": "Test User",
        "profiles": {}
    }
    
    # _save_json をモック化
    mock_bm._save_json = MagicMock()
    
    settings_manager.branding_manager = mock_bm
    
    yield mock_bm
    
    # 復元
    settings_manager.branding_manager = original_bm
    settings_manager.CONSTITUTION_PATH = original_const_path

@pytest.fixture
def mock_video_path(tmp_path):
    # settings_manager.VIDEO_SRC_PATH を一時フォルダのパスに変更する
    original_path = settings_manager.VIDEO_SRC_PATH
    test_video_path = tmp_path / "src" / "sample_raw.mp4"
    settings_manager.VIDEO_SRC_PATH = str(test_video_path)
    
    # フォルダを作成しておく
    test_video_path.parent.mkdir(parents=True, exist_ok=True)
    
    yield test_video_path
    
    # 復元
    settings_manager.VIDEO_SRC_PATH = original_path

@pytest.fixture
def test_manager():
    return SettingsManager()

def test_get_all_settings(test_manager, mock_branding_manager, mock_video_path):
    # ビデオが存在しない場合
    if os.path.exists(mock_video_path):
        os.remove(mock_video_path)
    
    res = test_manager.get_all_settings()
    assert res["constitution"] == mock_branding_manager.constitution
    assert res["user_model"] == mock_branding_manager.user_model
    assert res["video_exists"] is False
    
    # ビデオが存在する場合
    with open(mock_video_path, "w") as f:
        f.write("dummy")
    
    res2 = test_manager.get_all_settings()
    assert res2["video_exists"] is True

def test_get_video_source(test_manager, mock_video_path):
    assert test_manager.get_video_source() == str(mock_video_path)

def test_update_video_source_success(test_manager, mock_branding_manager, mock_video_path, tmp_path):
    # 新しいテンポラリビデオファイル
    temp_file = tmp_path / "temp_video.mp4"
    with open(temp_file, "w") as f:
        f.write("new content")
        
    # すでにビデオが存在する状態にする
    with open(mock_video_path, "w") as f:
        f.write("old content")
        
    res = test_manager.update_video_source(str(temp_file), original_filename="new_video.mp4")
    assert res["status"] == "success"
    assert res["filename"] == "new_video.mp4"
    
    # コピーされたか確認
    assert os.path.exists(mock_video_path)
    with open(mock_video_path, "r") as f:
        assert f.read() == "new content"
        
    # constitution が更新されて保存されたか確認
    assert mock_branding_manager.constitution["video_source_name"] == "new_video.mp4"
    mock_branding_manager._save_json.assert_called_once()

def test_update_video_source_error(test_manager, mock_branding_manager, mock_video_path):
    # 存在しないテンポラリファイルを渡すことでエラーを引き起こす
    res = test_manager.update_video_source("non_existent_file.mp4")
    assert res["status"] == "error"
    assert "message" in res

def test_update_identity(test_manager, mock_branding_manager):
    res = test_manager.update_identity(channel_name="New Channel", target_audience="New Audience")
    assert res["status"] == "success"
    assert mock_branding_manager.constitution["channel_name"] == "New Channel"
    assert mock_branding_manager.constitution["target_audience"] == "New Audience"
    mock_branding_manager._save_json.assert_called_once()

def test_export_soul_passport(test_manager, mock_branding_manager):
    assert test_manager.export_soul_passport() == mock_branding_manager.user_model

def test_reset_workspace_success(test_manager, mock_branding_manager, mock_video_path, tmp_path):
    # ビデオファイルとセグメントファイルを作成
    with open(mock_video_path, "w") as f:
        f.write("video")
        
    original_base = settings_manager.BASE_DIR
    # BASE_DIR もテスト用に tmp_path に一時変更する
    settings_manager.BASE_DIR = str(tmp_path)
    
    segments_path = tmp_path / "src" / "segments_a_plus_plus.json"
    segments_path.parent.mkdir(parents=True, exist_ok=True)
    with open(segments_path, "w") as f:
        f.write("segments")
        
    status_path = tmp_path / "src" / "transcription_status.json"
    
    try:
        res = test_manager.reset_workspace()
        assert res["status"] == "success"
        
        # ファイルが削除されたか確認
        assert not os.path.exists(mock_video_path)
        assert not os.path.exists(segments_path)
        
        # ステータスファイルが初期化されたか確認
        assert os.path.exists(status_path)
        with open(status_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
            assert status_data["status"] == "idle"
            
        # constitution が更新されたか確認
        assert mock_branding_manager.constitution["video_source_name"] == ""
        mock_branding_manager._save_json.assert_called_once()
        
    finally:
        # BASE_DIR を復元
        settings_manager.BASE_DIR = original_base

def test_reset_workspace_delete_permission_error_renaming_fallback(test_manager, mock_branding_manager, mock_video_path, tmp_path):
    # os.remove が PermissionError を吐いたときにリネームのフォールバックが機能するかテスト
    original_base = settings_manager.BASE_DIR
    settings_manager.BASE_DIR = str(tmp_path)
    
    with open(mock_video_path, "w") as f:
        f.write("video")
        
    segments_path = tmp_path / "src" / "segments_a_plus_plus.json"
    segments_path.parent.mkdir(parents=True, exist_ok=True)
    with open(segments_path, "w") as f:
        f.write("segments")
        
    # os.remove をモックして PermissionError を起こす
    def mock_remove(path):
        raise PermissionError("locked file")
        
    with patch("os.remove", side_effect=mock_remove), patch("os.rename") as mock_rename:
        res = test_manager.reset_workspace()
        assert res["status"] == "success"
        # os.rename が呼ばれたか確認
        assert mock_rename.call_count == 2 # video と segments 両方で呼ばれるはず
        
    settings_manager.BASE_DIR = original_base

def test_reset_workspace_delete_error(test_manager, mock_branding_manager, mock_video_path, tmp_path):
    original_base = settings_manager.BASE_DIR
    settings_manager.BASE_DIR = str(tmp_path)
    
    with open(mock_video_path, "w") as f:
        f.write("video")
        
    # os.remove と os.rename の両方が失敗する場合を模倣
    def mock_remove(path):
        raise PermissionError("locked file")
    
    def mock_rename(src, dst):
        raise OSError("cannot rename")
        
    with patch("os.remove", side_effect=mock_remove), patch("os.rename", side_effect=mock_rename):
        res = test_manager.reset_workspace()
        assert res["status"] == "error"
        assert "message" in res
        
    settings_manager.BASE_DIR = original_base

def test_reset_workspace_status_write_failure(test_manager, mock_branding_manager, tmp_path):
    # transcription_status.json 書き込みで例外を発生させる
    original_base = settings_manager.BASE_DIR
    settings_manager.BASE_DIR = str(tmp_path)
    
    # open関数をパッチし、STATUS_FILE_PATH が開かれたときに例外を投げるようにする
    original_open = open
    def mock_open_func(file, mode="r", *args, **kwargs):
        if "transcription_status.json" in str(file) and "w" in mode:
            raise IOError("Permission denied for transcription_status.json")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open_func):
        res = test_manager.reset_workspace()
        assert res["status"] == "success"  # 例外はキャッチされて pass されるため、正常終了する
        
    settings_manager.BASE_DIR = original_base

def test_import_fallback():
    # settings_manager を再ロードして ImportError フォールバックを確認する
    import sys
    
    # branding_manager がロードできないようにモックする
    with patch.dict(sys.modules, {'branding_manager': None}):
        # ただし、fallback先の 'branding.branding_manager' はインポート可能にする必要がある
        # ここでは sys.modules['branding.branding_manager'] もモックして、インポートさせる
        mock_bm_module = MagicMock()
        mock_bm_module.branding_manager = MagicMock()
        mock_bm_module.CONSTITUTION_PATH = "dummy_const_path"
        
        with patch.dict(sys.modules, {'branding.branding_manager': mock_bm_module}):
            # reload してフォールバック側を通す
            import settings_manager
            importlib.reload(settings_manager)


def test_update_identity_error(test_manager, mock_branding_manager):
    # branding_manager._save_json が例外を投げるようにモック
    mock_branding_manager._save_json.side_effect = RuntimeError("Save failure")
    res = test_manager.update_identity(channel_name="Err Channel", target_audience="Err Audience")
    assert res["status"] == "error"
    assert "Save failure" in res["message"]

def test_update_video_source_permission_error_fallback(test_manager, mock_branding_manager, mock_video_path, tmp_path):
    # 新しいテンポラリビデオファイル
    temp_file = tmp_path / "temp_video.mp4"
    with open(temp_file, "w") as f:
        f.write("new video data")
        
    # すでにビデオが存在する状態にする
    with open(mock_video_path, "w") as f:
        f.write("old video data")
        
    # os.remove をモックして PermissionError を起こす
    def mock_remove(path):
        raise PermissionError("locked file")
        
    with patch("os.remove", side_effect=mock_remove), patch("os.rename") as mock_rename:
        res = test_manager.update_video_source(str(temp_file), original_filename="new_video.mp4")
        assert res["status"] == "success"
        # shutil.move内でも os.rename が呼ばれる可能性があるため、引数を指定してアサートする
        found_rename = False
        for args, kwargs in mock_rename.call_args_list:
            if args[0] == str(mock_video_path) and ".trash_" in args[1]:
                found_rename = True
                break
        assert found_rename

def test_get_all_settings_none_fallback(test_manager, mock_branding_manager, mock_video_path):
    # constitution と user_model が None の場合
    mock_branding_manager.constitution = None
    mock_branding_manager.user_model = None
    
    # ビデオが存在しない場合
    if os.path.exists(mock_video_path):
        os.remove(mock_video_path)
        
    res = test_manager.get_all_settings()
    assert res["constitution"] == {}
    assert res["user_model"] == {}

def test_safe_delete_file_other_os_error(test_manager, mock_video_path):
    # os.remove が PermissionError 以外の OSError を吐くケース
    with open(mock_video_path, "w") as f:
        f.write("test content")
        
    def mock_remove(path):
        raise OSError("Generic OS error")
        
    with patch("os.remove", side_effect=mock_remove):
        with pytest.raises(OSError) as excinfo:
            test_manager._safe_delete_file(str(mock_video_path))
        assert "Generic OS error" in str(excinfo.value)
