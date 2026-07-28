"""backend/services/workspace_sync.py のテスト。

## 2026-07-28 に主張を全面的に書き換えた

旧テスト24件は、実装が「動くが何もしない」モックであることを**正解として
固定していた**。たとえば偽の Drive リンクの生成規則がアサーションだった。

    assert "https://drive.google.com/file/d/drv_test_video_id/view" == link_success

同様に「API 失敗時にスタブを返して True」も期待値として書かれていた。
実装をやめたので、テストの主張も入れ替えている。いまの主張は逆で、
**失敗したら例外が上がること**を確かめる。

Google には一切接続しない。サービスクライアントは差し替える。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.workspace_sync import (
    GoogleDriveStore,
    GoogleSheetsStore,
    WorkspacePipelineRunner,
    WorkspaceSyncError,
    temp_raw_videos_dir,
)


@pytest.fixture(autouse=True)
def isolated_temp_dir(monkeypatch, tmp_path):
    """一時置き場をテストごとに隔離する。

    旧テストはカレントディレクトリに `temp_raw_videos/` を作って後片付け
    していた。並列実行で踏み合うので環境変数で振り向ける。
    """
    monkeypatch.setenv("ANTIGRAVITY_TEMP_RAW_VIDEOS", str(tmp_path / "temp_raw_videos"))


# ---------------- 一時置き場の解決 ----------------

def test_temp_dir_follows_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIGRAVITY_TEMP_RAW_VIDEOS", str(tmp_path / "x"))
    assert temp_raw_videos_dir() == tmp_path / "x"


def test_temp_dir_is_not_cwd_relative(monkeypatch, tmp_path):
    """カレントディレクトリ依存だと実行場所で書き込み先が変わる。"""
    monkeypatch.delenv("ANTIGRAVITY_TEMP_RAW_VIDEOS", raising=False)
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path))
    assert temp_raw_videos_dir().is_absolute()
    assert temp_raw_videos_dir() == tmp_path / "temp_raw_videos"


# ---------------- 引数の検証 ----------------

def test_sheets_store_requires_spreadsheet_id():
    with pytest.raises(ValueError):
        GoogleSheetsStore(spreadsheet_id="")


def test_drive_store_requires_folder_id():
    with pytest.raises(ValueError):
        GoogleDriveStore(root_folder_id="")


# ---------------- Sheets ----------------

def _sheets_store_with(values_mock):
    store = GoogleSheetsStore(spreadsheet_id="sheet_123", user_email="u@example.com")
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value = values_mock
    store._service = service
    return store


def test_read_config_parses_key_value_rows():
    values = MagicMock()
    values.get.return_value.execute.return_value = {
        "values": [["nhk_max_chars", "15"], ["quality_threshold", "80"], ["preferred_voice", "ja-JP-Wavenet-D"]]
    }
    store = _sheets_store_with(values)

    config = store.read_config("NHK_Settings")

    assert config["nhk_max_chars"] == 15
    assert config["quality_threshold"] == 80
    assert config["preferred_voice"] == "ja-JP-Wavenet-D"
    # 実際にシートを読んでいる（旧実装はハードコードを返していた）
    assert values.get.call_args.kwargs["range"] == "NHK_Settings!A:B"
    assert values.get.call_args.kwargs["spreadsheetId"] == "sheet_123"


def test_read_config_coerces_types():
    values = MagicMock()
    values.get.return_value.execute.return_value = {
        "values": [["ratio", "0.85"], ["enabled", "true"], ["off", "FALSE"], ["name", "abc"]]
    }
    config = _sheets_store_with(values).read_config("S")

    assert config["ratio"] == 0.85
    assert config["enabled"] is True
    assert config["off"] is False
    assert config["name"] == "abc"


def test_read_config_skips_blank_rows_and_missing_values():
    values = MagicMock()
    values.get.return_value.execute.return_value = {
        "values": [[], ["", "x"], ["lonely_key"]]
    }
    config = _sheets_store_with(values).read_config("S")

    assert config == {"lonely_key": ""}


def test_read_config_raises_on_api_failure():
    """旧実装はここでハードコードされた設定を返していた。"""
    values = MagicMock()
    values.get.return_value.execute.side_effect = OSError("boom")
    with pytest.raises(WorkspaceSyncError):
        _sheets_store_with(values).read_config("S")


def test_update_progress_updates_existing_row():
    values = MagicMock()
    values.get.return_value.execute.return_value = {"values": [["task_a"], ["task_b"], ["task_c"]]}
    store = _sheets_store_with(values)

    assert store.update_progress("task_b", 50, "PROCESSING", "note") is True

    # 2行目を更新している（1始まり）
    assert values.update.call_args.kwargs["range"] == "Progress!A2:D2"
    assert values.update.call_args.kwargs["body"]["values"] == [["task_b", 50, "PROCESSING", "note"]]
    values.append.assert_not_called()


def test_update_progress_appends_when_task_is_new():
    values = MagicMock()
    values.get.return_value.execute.return_value = {"values": [["task_a"]]}
    store = _sheets_store_with(values)

    store.update_progress("task_new", 0, "STARTING", "")

    values.append.assert_called_once()
    assert values.append.call_args.kwargs["body"]["values"] == [["task_new", 0, "STARTING", ""]]
    values.update.assert_not_called()


def test_update_progress_raises_on_api_failure():
    """旧実装は print して True を返すだけだった。"""
    values = MagicMock()
    values.get.return_value.execute.side_effect = OSError("network down")
    with pytest.raises(WorkspaceSyncError):
        _sheets_store_with(values).update_progress("t", 1, "S")


def test_progress_tab_is_configurable(monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_SHEETS_PROGRESS_TAB", "進捗")
    values = MagicMock()
    values.get.return_value.execute.return_value = {"values": []}
    _sheets_store_with(values).update_progress("t", 1, "S")
    assert values.append.call_args.kwargs["range"] == "進捗!A:D"


# ---------------- Drive: 列挙 ----------------

def _drive_store_with(service):
    store = GoogleDriveStore(root_folder_id="folder_123", user_email="u@example.com")
    store._service = service
    return store


def test_list_input_raw_videos_returns_api_results():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f_999", "name": "real_raw.mp4", "size": 9999}]
    }
    videos = _drive_store_with(service).list_input_raw_videos()

    assert videos == [{"id": "f_999", "name": "real_raw.mp4", "size": 9999}]


def test_list_input_raw_videos_follows_pagination():
    """100件を超えるフォルダで取りこぼさない。"""
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "a"}], "nextPageToken": "p2"},
        {"files": [{"id": "b"}], "nextPageToken": "p3"},
        {"files": [{"id": "c"}]},
    ]
    videos = _drive_store_with(service).list_input_raw_videos()

    assert [v["id"] for v in videos] == ["a", "b", "c"]


def test_list_input_raw_videos_raises_on_api_failure():
    """旧実装はスタブ2件を返していた。実在しない動画を処理し始めてしまう。"""
    service = MagicMock()
    service.files.return_value.list.side_effect = OSError("API connection error")
    with pytest.raises(WorkspaceSyncError):
        _drive_store_with(service).list_input_raw_videos()


def test_list_query_scopes_to_folder_and_excludes_trash():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    _drive_store_with(service).list_input_raw_videos()

    query = service.files.return_value.list.call_args.kwargs["q"]
    assert "'folder_123' in parents" in query
    assert "trashed = false" in query
    assert "video/mp4" in query


# ---------------- Drive: ダウンロード ----------------

class _Status:
    def __init__(self, prog):
        self._prog = prog

    def progress(self):
        return self._prog


def test_download_succeeds(tmp_path):
    dest = tmp_path / "dest.mp4"
    downloader = MagicMock()
    downloader.next_chunk.side_effect = [(_Status(0.5), False), (_Status(1.0), True)]

    store = _drive_store_with(MagicMock())
    with patch("googleapiclient.http.MediaIoBaseDownload", return_value=downloader):
        assert store.download_file_chunked("f_1", dest) is True
    assert dest.exists()


def test_download_retries_then_succeeds(tmp_path):
    dest = tmp_path / "dest.mp4"
    downloader = MagicMock()
    downloader.next_chunk.side_effect = [OSError("Connection lost"), (_Status(1.0), True)]

    store = _drive_store_with(MagicMock())
    with patch("googleapiclient.http.MediaIoBaseDownload", return_value=downloader), \
         patch("time.sleep"):
        assert store.download_file_chunked("f_1", dest) is True


def test_download_raises_after_retries_exhausted(tmp_path):
    """旧実装はここでテキストを .mp4 として書き True を返していた。"""
    dest = tmp_path / "dest.mp4"
    downloader = MagicMock()
    downloader.next_chunk.side_effect = OSError("Persistent connection issue")

    store = _drive_store_with(MagicMock())
    with patch("googleapiclient.http.MediaIoBaseDownload", return_value=downloader), \
         patch("time.sleep"), \
         pytest.raises(WorkspaceSyncError):
        store.download_file_chunked("f_1", dest)


def test_failed_download_leaves_no_partial_file(tmp_path):
    """書きかけのファイルが残ると「落とせた」と誤認される。"""
    dest = tmp_path / "dest.mp4"
    downloader = MagicMock()
    downloader.next_chunk.side_effect = OSError("boom")

    store = _drive_store_with(MagicMock())
    with patch("googleapiclient.http.MediaIoBaseDownload", return_value=downloader), \
         patch("time.sleep"), \
         pytest.raises(WorkspaceSyncError):
        store.download_file_chunked("f_1", dest)
    assert not dest.exists()


def test_download_asset_uses_the_same_path(tmp_path):
    dest = tmp_path / "bgm.mp3"
    store = _drive_store_with(MagicMock())
    with patch.object(store, "download_file_chunked", return_value=True) as m:
        assert store.download_asset("asset_1", dest) is True
    m.assert_called_once_with("asset_1", dest)


# ---------------- Drive: アップロード ----------------

def test_upload_video_actually_calls_the_api(tmp_path):
    """旧実装は API を呼ばず、偽リンクを組み立てて返していた。"""
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")

    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {
        "id": "real_id", "webViewLink": "https://drive.google.com/file/d/real_id/view"
    }
    store = _drive_store_with(service)

    with patch("googleapiclient.http.MediaFileUpload") as media:
        link = store.upload_video(video)

    assert link == "https://drive.google.com/file/d/real_id/view"
    service.files.return_value.create.assert_called_once()
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["name"] == "out.mp4"
    assert body["parents"] == ["folder_123"]
    media.assert_called_once()


def test_upload_video_falls_back_to_constructed_link_when_absent(tmp_path):
    """webViewLink が返らなくても、実在する ID からリンクを作るのは可。"""
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "abc"}

    with patch("googleapiclient.http.MediaFileUpload"):
        link = _drive_store_with(service).upload_video(video)
    assert link == "https://drive.google.com/file/d/abc/view"


def test_upload_video_raises_when_response_has_no_id(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {}

    with patch("googleapiclient.http.MediaFileUpload"), \
         pytest.raises(WorkspaceSyncError):
        _drive_store_with(service).upload_video(video)


def test_upload_video_raises_when_local_file_missing(tmp_path):
    with pytest.raises(WorkspaceSyncError):
        _drive_store_with(MagicMock()).upload_video(tmp_path / "nope.mp4")


def test_upload_video_raises_on_api_failure(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    service = MagicMock()
    service.files.return_value.create.side_effect = OSError("quota exceeded")

    with patch("googleapiclient.http.MediaFileUpload"), \
         pytest.raises(WorkspaceSyncError):
        _drive_store_with(service).upload_video(video)


# ---------------- Drive: 後始末 ----------------

def test_cleanup_removes_file(tmp_path):
    f = tmp_path / "raw.mp4"
    f.write_text("x", encoding="utf-8")
    assert _drive_store_with(MagicMock()).cleanup_local_raw_video(f) is True
    assert not f.exists()


def test_cleanup_returns_false_when_absent(tmp_path):
    assert _drive_store_with(MagicMock()).cleanup_local_raw_video(tmp_path / "nope.mp4") is False


def test_cleanup_returns_false_on_permission_error(tmp_path):
    """消せなくてもパイプラインは成立する。ここは例外にしない。"""
    f = tmp_path / "raw.mp4"
    f.write_text("x", encoding="utf-8")
    with patch("os.remove", side_effect=PermissionError("locked")):
        assert _drive_store_with(MagicMock()).cleanup_local_raw_video(f) is False


# ---------------- パイプライン ----------------

def _runner(executor, drive=None, sheets=None):
    return WorkspacePipelineRunner(sheets or MagicMock(), drive or MagicMock(), executor)


def test_runner_returns_false_when_no_videos():
    drive = MagicMock()
    drive.list_input_raw_videos.return_value = []
    assert _runner(lambda a, b: None, drive=drive).run_pipeline_for_next_video() is False


def test_runner_happy_path():
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "test_raw.mp4", "size": 500}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download
    drive.upload_video.return_value = "https://drive.google.com/file/d/real/view"

    def executor(src, out):
        assert src.exists()
        out.write_text("processed", encoding="utf-8")
        return out

    assert _runner(executor, drive, sheets).run_pipeline_for_next_video() is True

    sheets.update_progress.assert_any_call("task_v_001", 0, "STARTING", "Starting processing for test_raw.mp4")
    sheets.update_progress.assert_any_call("task_v_001", 100, "COMPLETED", "Completed. Drive Link: https://drive.google.com/file/d/real/view")
    drive.cleanup_local_raw_video.assert_called_once()


def test_runner_reports_failure_when_download_raises():
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]
    drive.download_file_chunked.side_effect = WorkspaceSyncError("download failed")

    assert _runner(lambda a, b: None, drive, sheets).run_pipeline_for_next_video() is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: download failed")


def test_runner_fails_when_pipeline_produces_nothing():
    """旧実装はスタブを書いて先へ進み、テキストの .mp4 を納品していた。"""
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download

    assert _runner(lambda a, b: None, drive, sheets).run_pipeline_for_next_video() is False
    drive.upload_video.assert_not_called()


def test_runner_fails_when_pipeline_output_is_empty():
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download

    def executor(src, out):
        out.write_bytes(b"")
        return out

    assert _runner(executor, drive, sheets).run_pipeline_for_next_video() is False
    drive.upload_video.assert_not_called()


def test_runner_reports_failure_when_upload_raises():
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download
    drive.upload_video.side_effect = WorkspaceSyncError("upload failed")

    def executor(src, out):
        out.write_text("processed", encoding="utf-8")
        return out

    assert _runner(executor, drive, sheets).run_pipeline_for_next_video() is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: upload failed")


def test_runner_survives_executor_crash():
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download
    executor = MagicMock(side_effect=RuntimeError("Unexpected crash"))

    assert _runner(executor, drive, sheets).run_pipeline_for_next_video() is False
    sheets.update_progress.assert_any_call("task_v_001", -1, "FAILED", "Error: Unexpected crash")


def test_runner_does_not_hide_original_failure_when_reporting_also_fails(caplog):
    """Drive が落ちていれば Sheets も落ちている。元の失敗を消さない。"""
    import logging
    caplog.set_level(logging.ERROR)

    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]
    drive.download_file_chunked.side_effect = WorkspaceSyncError("original failure")

    # 失敗の記録（progress=-1）だけを落とす。STARTING まで落とすと
    # ダウンロードに到達せず、確かめたい状況にならない。
    def only_failure_write_breaks(task_id, pct, status, notes=""):
        if pct == -1:
            raise WorkspaceSyncError("sheets also down")
        return True

    sheets.update_progress.side_effect = only_failure_write_breaks

    assert _runner(lambda a, b: None, drive, sheets).run_pipeline_for_next_video() is False
    assert "original failure" in caplog.text


def test_runner_cleans_up_output_on_success():
    drive = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]
    produced = {}

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download
    drive.upload_video.return_value = "https://drive.google.com/file/d/x/view"

    def executor(src, out):
        out.write_text("processed", encoding="utf-8")
        produced["out"] = out
        return out

    assert _runner(executor, drive).run_pipeline_for_next_video() is True
    assert not produced["out"].exists()
