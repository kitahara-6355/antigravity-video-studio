# -*- coding: utf-8 -*-
import pytest
from pathlib import Path
import os
import sys
import shutil
from unittest.mock import MagicMock, patch

# パス設定: backend の親(プロジェクトルート)を sys.path に追加して backend.* 経由のインポートを可能にする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.workspace_sync import (
    GoogleSheetsStore,
    GoogleDriveStore,
    WorkspacePipelineRunner,
    HAS_GOOGLE_API
)

@pytest.fixture(autouse=True)
def cleanup_temp_dir():
    yield
    # テスト実行後に作成された一時ディレクトリを削除
    temp_dir = Path("temp_raw_videos")
    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass


def test_workspace_sheets_store(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text("{}", encoding="utf-8")
    
    store = GoogleSheetsStore(
        spreadsheet_id="test_sheet_123",
        credentials_path=str(cred_file),
        user_email="test_user@gmail.com"
    )
    
    assert store.spreadsheet_id == "test_sheet_123"
    assert store.user_email == "test_user@gmail.com"
    
    assert "[Workspace Sync] Loading OAuth credentials" in caplog.text
    assert "Authenticated as Google user: test_user@gmail.com" in caplog.text

    config = store.read_config("NHK_Settings")
    assert config["nhk_max_chars"] == 15
    assert "Action: READ_CONFIG" in caplog.text

    success = store.update_progress("task_001", 50, "RUNNING", "Rendering segment")
    assert success is True
    assert "Action: UPDATE_PROGRESS" in caplog.text


def test_workspace_drive_store(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text("{}", encoding="utf-8")
    
    store = GoogleDriveStore(
        root_folder_id="drive_folder_abc",
        credentials_path=str(cred_file),
        user_email="test_user@gmail.com"
    )
    
    assert store.root_folder_id == "drive_folder_abc"
    assert "[Drive Sync] Using credentials" in caplog.text
    
    non_existent = Path("non_existent.mp4")
    link_fail = store.upload_video(non_existent)
    assert link_fail is None
    assert "[Drive Sync] Upload failed" in caplog.text

    dummy_video = tmp_path / "test_video.mp4"
    dummy_video.write_text("dummy video data", encoding="utf-8")
    
    link_success = store.upload_video(dummy_video)
    assert link_success is not None
    assert "https://drive.google.com/file/d/drv_test_video_id/view" == link_success
    assert "Action: UPLOAD_VIDEO" in caplog.text

    dl_success = store.download_asset("asset_bgm_01", tmp_path / "bgm.mp3")
    assert dl_success is True
    assert "Action: DOWNLOAD_ASSET" in caplog.text


# ---- 新規追加テスト ----

def test_list_input_raw_videos_no_api():
    store = GoogleDriveStore(root_folder_id="folder_123")
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", False):
        videos = store.list_input_raw_videos()
        assert len(videos) == 2
        assert videos[0]["id"] == "stub_video_001"
        assert videos[0]["name"] == "stub_raw_1.mp4"


def test_list_input_raw_videos_has_api_success():
    store = GoogleDriveStore(root_folder_id="folder_123")
    
    mock_service = MagicMock()
    mock_execute = MagicMock(return_value={"files": [{"id": "f_999", "name": "real_raw.mp4", "size": 9999}]})
    mock_service.files().list().execute = mock_execute
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=mock_service):
        
        videos = store.list_input_raw_videos()
        assert len(videos) == 1
        assert videos[0]["id"] == "f_999"
        assert videos[0]["name"] == "real_raw.mp4"


def test_list_input_raw_videos_api_failure():
    
    store = GoogleDriveStore(root_folder_id="folder_123")
    
    # サービス取得は成功するがAPI実行で例外
    mock_service = MagicMock()
    mock_service.files().list.side_effect = OSError("API connection error")
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=mock_service):
        
        videos = store.list_input_raw_videos()
        assert len(videos) == 2  # スタブにフォールバック
        assert videos[0]["id"] == "stub_video_001"



def test_get_service_exception(tmp_path):
    
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text("{}", encoding="utf-8")
    
    store = GoogleDriveStore(root_folder_id="folder_123", credentials_path=str(cred_file))
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch("google.oauth2.service_account.Credentials.from_service_account_file", side_effect=ValueError("Failed to load creds")):
        
        service = store._get_service()
        assert service is None



def test_download_file_chunked_no_api(tmp_path):
    store = GoogleDriveStore(root_folder_id="folder_123")
    dest = tmp_path / "dest.mp4"
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", False):
        success = store.download_file_chunked("file_123", dest)
        assert success is True
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "stub_video_content"


class MockDownloadStatus:
    def __init__(self, prog):
        self._prog = prog
    def progress(self):
        return self._prog


def test_download_file_chunked_has_api_success(tmp_path):
    store = GoogleDriveStore(root_folder_id="folder_123")
    dest = tmp_path / "dest.mp4"
    
    mock_service = MagicMock()
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.side_effect = [
        (MockDownloadStatus(0.5), False),
        (MockDownloadStatus(1.0), True)
    ]
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=mock_service), \
         patch("backend.services.workspace_sync.MediaIoBaseDownload", return_value=mock_downloader):
        
        success = store.download_file_chunked("real_file_123", dest)
        assert success is True
        assert dest.exists()


def test_download_file_chunked_retry_and_success(tmp_path):
    store = GoogleDriveStore(root_folder_id="folder_123")
    dest = tmp_path / "dest.mp4"
    
    mock_service = MagicMock()
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.side_effect = [
        OSError("Connection lost"),
        (MockDownloadStatus(1.0), True)
    ]
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=mock_service), \
         patch("backend.services.workspace_sync.MediaIoBaseDownload", return_value=mock_downloader), \
         patch("time.sleep"):
        
        success = store.download_file_chunked("real_file_123", dest)
        assert success is True
        assert dest.exists()


def test_download_file_chunked_api_failure_fallback(tmp_path):
    
    store = GoogleDriveStore(root_folder_id="folder_123")
    dest = tmp_path / "dest.mp4"
    
    mock_service = MagicMock()
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.side_effect = OSError("Persistent connection issue")
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=mock_service), \
         patch("backend.services.workspace_sync.MediaIoBaseDownload", return_value=mock_downloader), \
         patch("time.sleep"):
        
        success = store.download_file_chunked("real_file_123", dest)
        assert success is True  # フォールバックしてダミーファイルを書き込むためTrue
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "stub_video_content_fallback"



def test_cleanup_local_raw_video(tmp_path):
    store = GoogleDriveStore(root_folder_id="folder_123")
    
    # 正常系
    test_file = tmp_path / "cleanup_test.mp4"
    test_file.write_text("dummy raw", encoding="utf-8")
    assert test_file.exists()
    assert store.cleanup_local_raw_video(test_file) is True
    assert not test_file.exists()
    
    # FileNotFoundError (exists() == False のためログ出力して False)
    assert store.cleanup_local_raw_video(test_file) is False

    # exists() == True だが os.remove() で FileNotFoundError が発生する場合
    test_file.write_text("dummy raw 2", encoding="utf-8")
    with patch("os.remove", side_effect=FileNotFoundError("Mock error")):
        assert store.cleanup_local_raw_video(test_file) is False

    # PermissionError
    with patch("os.remove", side_effect=PermissionError("Mock permission error")):
        assert store.cleanup_local_raw_video(test_file) is False


def test_runner_no_videos():
    sheets = MagicMock()
    drive = MagicMock()
    drive.list_input_raw_videos.return_value = []
    
    runner = WorkspacePipelineRunner(sheets, drive, lambda x, y: None)
    assert runner.run_pipeline_for_next_video() is False


def test_runner_workflow_success(tmp_path):
    sheets = MagicMock()
    drive = MagicMock()
    
    video_id = "v_001"
    video_name = "test_raw.mp4"
    drive.list_input_raw_videos.return_value = [{"id": video_id, "name": video_name, "size": 500}]
    
    # download_file_chunked で実際にファイルを生成
    def mock_download(file_id, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock raw content", encoding="utf-8")
        return True
    drive.download_file_chunked.side_effect = mock_download
    
    drive.upload_video.return_value = "https://drive.google.com/file/d/drv_processed_id/view"
    
    # executorの動作: 元ファイルを確認し、成果物を書き出す
    def mock_executor(in_path, out_path):
        assert in_path.exists()
        out_path.write_text("mock processed content", encoding="utf-8")
        return out_path
        
    runner = WorkspacePipelineRunner(sheets, drive, mock_executor)
    
    # 一時ディレクトリがクリーンアップされることの確認を含めて実行
    success = runner.run_pipeline_for_next_video()
    assert success is True
    
    # update_progressが正しく呼ばれたか
    sheets.update_progress.assert_any_call("task_v_001", 0, "STARTING", "Starting processing for test_raw.mp4")
    sheets.update_progress.assert_any_call("task_v_001", 20, "DOWNLOADED", "Raw video downloaded locally")
    sheets.update_progress.assert_any_call("task_v_001", 50, "PROCESSING", "Executing local pipeline")
    sheets.update_progress.assert_any_call("task_v_001", 90, "UPLOADED", "Processed video uploaded to Drive")
    sheets.update_progress.assert_any_call("task_v_001", 100, "COMPLETED", "Completed. Drive Link: https://drive.google.com/file/d/drv_processed_id/view")
    
    # クリーンアップの呼び出し検証
    drive.cleanup_local_raw_video.assert_called_once()


def test_runner_workflow_download_failed():
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    drive.download_file_chunked.return_value = False
    
    runner = WorkspacePipelineRunner(sheets, drive, lambda x, y: None)
    success = runner.run_pipeline_for_next_video()
    assert success is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: Failed to download raw video test_raw.mp4")


def test_runner_workflow_upload_failed():
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    
    def mock_download(file_id, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock raw content", encoding="utf-8")
        return True
    drive.download_file_chunked.side_effect = mock_download
    drive.upload_video.return_value = None  # アップロード失敗
    
    runner = WorkspacePipelineRunner(sheets, drive, lambda x, y: None)
    success = runner.run_pipeline_for_next_video()
    assert success is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: Failed to upload processed video")


def test_runner_workflow_unexpected_exception():
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    drive.download_file_chunked.return_value = True
    
    # 想定外の例外をスローする executor
    mock_executor = MagicMock(side_effect=RuntimeError("Unexpected crash"))
    
    runner = WorkspacePipelineRunner(sheets, drive, mock_executor)
    success = runner.run_pipeline_for_next_video()
    assert success is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: Unexpected crash")


# ---- カバレッジ100%達成のための追加テスト ----

def test_workspace_sync_no_google_api_import_fallback():
    import sys
    import importlib
    
    # googleapiclient.discovery と googleapiclient.http, google.auth を sys.modules から一時的に取り除く
    modules_to_restore = {}
    for mod in ["googleapiclient.discovery", "googleapiclient.http", "google.auth"]:
        if mod in sys.modules:
            modules_to_restore[mod] = sys.modules[mod]
            sys.modules[mod] = None
    
    try:
        import backend.services.workspace_sync as ws
        importlib.reload(ws)
        
        assert ws.HAS_GOOGLE_API is False
        
        # この状態で _get_service() が None を返すことを確認
        store = ws.GoogleDriveStore(root_folder_id="folder_123", credentials_path="dummy.json")
        assert store._get_service() is None
    finally:
        # モジュールを元に戻す
        for mod, val in modules_to_restore.items():
            if val is None:
                sys.modules.pop(mod, None)
            else:
                sys.modules[mod] = val
        import backend.services.workspace_sync as ws
        importlib.reload(ws)


def test_get_service_no_credentials():
    store = GoogleDriveStore(root_folder_id="folder_123", credentials_path=None)
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True):
        assert store._get_service() is None


def test_get_service_success_build(tmp_path):
    cred_file = tmp_path / "credentials.json"
    cred_file.write_text("{}", encoding="utf-8")
    store = GoogleDriveStore(root_folder_id="folder_123", credentials_path=str(cred_file))
    
    mock_creds = MagicMock()
    mock_build = MagicMock()
    
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch("google.oauth2.service_account.Credentials") as mock_creds_class, \
         patch("backend.services.workspace_sync.build", return_value=mock_build) as mock_b:
        
        mock_creds_class.from_service_account_file.return_value = mock_creds
        service = store._get_service()
        assert service == mock_build
        mock_b.assert_called_once_with("drive", "v3", credentials=mock_creds)


def test_list_videos_no_service():
    store = GoogleDriveStore(root_folder_id="folder_123")
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=None):
        
        videos = store.list_input_raw_videos()
        assert len(videos) == 2
        assert videos[0]["id"] == "stub_video_001"


def test_download_file_no_service(tmp_path):
    store = GoogleDriveStore(root_folder_id="folder_123")
    dest = tmp_path / "dest.mp4"
    with patch("backend.services.workspace_sync.HAS_GOOGLE_API", True), \
         patch.object(store, "_get_service", return_value=None):
        
        success = store.download_file_chunked("file_123", dest)
        assert success is True
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "stub_video_content"


def test_runner_workflow_success_remove_output_error(tmp_path):
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    
    def mock_download(file_id, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock raw content", encoding="utf-8")
        return True
    drive.download_file_chunked.side_effect = mock_download
    drive.upload_video.return_value = "https://drive.google.com/file/d/drv_processed_id/view"
    
    def mock_executor(in_path, out_path):
        out_path.write_text("mock processed content", encoding="utf-8")
        return out_path
        
    runner = WorkspacePipelineRunner(sheets, drive, mock_executor)
    
    original_remove = os.remove
    def mock_remove(path):
        if "processed_test_raw.mp4" in str(path):
            raise OSError("Mock output remove error")
        return original_remove(path)
        
    with patch("os.remove", side_effect=mock_remove):
        success = runner.run_pipeline_for_next_video()
        assert success is True


def test_runner_workflow_download_failed_remove_output_error(tmp_path):
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    drive.download_file_chunked.return_value = False
    
    runner = WorkspacePipelineRunner(sheets, drive, lambda x, y: None)
    
    # 物理的に一時ファイルと出力ファイルを作成しておく
    temp_dir = Path("temp_raw_videos")
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest_file = temp_dir / "test_raw.mp4"
    dest_file.write_text("dummy", encoding="utf-8")
    out_file = temp_dir / "processed_test_raw.mp4"
    out_file.write_text("dummy", encoding="utf-8")
    
    with patch("os.remove", side_effect=OSError("Mock remove error during rollback")):
        success = runner.run_pipeline_for_next_video()
        assert success is False
        
    # クリーンアップ
    if dest_file.exists():
        try: os.remove(dest_file)
        except OSError: pass
    if out_file.exists():
        try: os.remove(out_file)
        except OSError: pass


def test_runner_workflow_unexpected_exception_remove_errors(tmp_path):
    sheets = MagicMock()
    drive = MagicMock()
    
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]
    drive.download_file_chunked.return_value = True
    
    mock_executor = MagicMock(side_effect=RuntimeError("Unexpected crash"))
    runner = WorkspacePipelineRunner(sheets, drive, mock_executor)
    
    # 物理的にファイルを作成しておく
    temp_dir = Path("temp_raw_videos")
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest_file = temp_dir / "test_raw.mp4"
    dest_file.write_text("dummy", encoding="utf-8")
    out_file = temp_dir / "processed_test_raw.mp4"
    out_file.write_text("dummy", encoding="utf-8")
    
    with patch("os.remove", side_effect=OSError("Mock remove error on unexpected exception rollback")):
        success = runner.run_pipeline_for_next_video()
        assert success is False
        drive.cleanup_local_raw_video.assert_called_once()

    # クリーンアップ
    if dest_file.exists():
        try: os.remove(dest_file)
        except OSError: pass
    if out_file.exists():
        try: os.remove(out_file)
        except OSError: pass
