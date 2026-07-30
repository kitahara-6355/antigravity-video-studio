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
import logging
import os
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.workspace_sync import (
    DOWNLOAD_CHUNK_SIZE,
    GoogleDriveStore,
    GoogleSheetsStore,
    InsufficientDiskSpaceError,
    WorkspacePipelineRunner,
    WorkspaceSyncError,
    ensure_disk_space,
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

def _drive_store_with(service, output_folder_id="out_456"):
    store = GoogleDriveStore(
        root_folder_id="folder_123",
        output_folder_id=output_folder_id,
        user_email="u@example.com",
    )
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
    # 入力フォルダ(folder_123)ではなく出力フォルダへ入れる。
    # 入力に書き戻すと次回の未処理 RAW として拾われ、無限に再処理される。
    assert body["parents"] == ["out_456"]
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
    # 作業ディレクトリごと消えている。以前はファイル単位で消していたため、
    # executor が想定外の中間ファイルを置くと残り続けた。
    assert not (temp_raw_videos_dir() / "task_v_001").exists()


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


# ---------------- 出力フォルダの分離 ----------------

def test_upload_refuses_when_output_folder_unset(tmp_path):
    """出力先が無いとき、入力フォルダに書き戻さず失敗する。

    書き戻すと成果物が次回の未処理 RAW として拾われ、無限に再処理される。
    旧実装は `dest_folder_id or self.root_folder_id` で黙って入力へ入れていた。
    """
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    store = _drive_store_with(MagicMock(), output_folder_id=None)

    with pytest.raises(WorkspaceSyncError, match="出力フォルダ"):
        store.upload_video(video)


def test_upload_prefers_explicit_dest_over_configured_output(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "i"}
    store = _drive_store_with(service)

    with patch("googleapiclient.http.MediaFileUpload"):
        store.upload_video(video, dest_folder_id="explicit_789")

    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["parents"] == ["explicit_789"]


def test_upload_warns_when_output_equals_input(tmp_path, caplog):
    """明示的に入力と同じにした場合は通すが、警告を残す。"""
    video = tmp_path / "out.mp4"
    video.write_bytes(b"data")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "i"}
    store = _drive_store_with(service, output_folder_id="folder_123")

    with caplog.at_level(logging.WARNING), patch("googleapiclient.http.MediaFileUpload"):
        store.upload_video(video)

    assert "入力フォルダと同じ" in caplog.text


def test_constructor_rejects_positional_output_folder():
    """位置引数を許すと user_email が出力フォルダとして解釈され静かに壊れる。"""
    with pytest.raises(TypeError):
        GoogleDriveStore("folder_123", "u@example.com")  # type: ignore[misc]


# ---------------- ダウンロードのチャンクサイズ ----------------

def test_download_uses_large_chunk_size(tmp_path):
    """1 MB では往復回数が律速になる（239 MB で実測 172 秒 → 64 MB なら 11 秒）。"""
    assert DOWNLOAD_CHUNK_SIZE == 64 * 1024 * 1024

    store = _drive_store_with(MagicMock())
    dest = tmp_path / "v.mp4"

    with patch("googleapiclient.http.MediaIoBaseDownload") as dl:
        dl.return_value.next_chunk.return_value = (MagicMock(), True)
        store.download_file_chunked("fid", dest)

    assert dl.call_args.kwargs["chunksize"] == DOWNLOAD_CHUNK_SIZE


# ---------------- 空き容量の事前チェック ----------------

def test_ensure_disk_space_passes_when_enough(tmp_path):
    ensure_disk_space(tmp_path, 1)


def test_ensure_disk_space_raises_when_short(tmp_path):
    with pytest.raises(InsufficientDiskSpaceError, match="空き容量が足りません"):
        ensure_disk_space(tmp_path, 10**18)


def test_runner_checks_disk_before_downloading():
    """容量不足なら、ダウンロードを始める前に落とす。

    始めてしまうと原本は落ちても中間生成で力尽き、原因が容量だと分かりにくい。
    """
    drive = MagicMock()
    sheets = MagicMock()
    drive.list_input_raw_videos.return_value = [
        {"id": "v_001", "name": "huge.mp4", "size": 10**17}
    ]

    assert _runner(lambda a, b: None, drive, sheets).run_pipeline_for_next_video() is False
    drive.download_file_chunked.assert_not_called()
    status = [c.args[2] for c in sheets.update_progress.call_args_list]
    assert "FAILED" in status


def test_runner_requires_headroom_beyond_raw_size(monkeypatch, tmp_path):
    """原本ぶんだけでは足りない。中間ファイルと出力ぶんの余裕を要求する。"""
    monkeypatch.setenv("ANTIGRAVITY_TEMP_RAW_VIDEOS", str(tmp_path / "t"))
    drive = MagicMock()
    size = 100
    drive.list_input_raw_videos.return_value = [
        {"id": "v_001", "name": "t.mp4", "size": size}
    ]
    calls = []

    def fake_usage(path):
        calls.append(path)
        return SimpleNamespace(total=0, used=0, free=size * 2)  # 2倍しかない

    monkeypatch.setattr(shutil, "disk_usage", fake_usage)
    assert _runner(lambda a, b: None, drive).run_pipeline_for_next_video() is False
    drive.download_file_chunked.assert_not_called()
    assert calls, "空き容量を確認していない"


# ---------------- ジョブ単位の作業ディレクトリ ----------------

def test_job_dir_is_scoped_per_task():
    """同名 RAW の別ジョブが踏み合わないよう、task_id でディレクトリを分ける。"""
    drive = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_042", "name": "t.mp4", "size": 5}]
    seen = {}

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        seen["dir"] = dest.parent
        return True

    drive.download_file_chunked.side_effect = download
    drive.upload_video.return_value = "https://drive.google.com/file/d/x/view"

    _runner(lambda s, o: o.write_text("p", encoding="utf-8") or o, drive).run_pipeline_for_next_video()

    assert seen["dir"].name == "task_v_042"
    assert seen["dir"].parent == temp_raw_videos_dir()


def test_job_dir_removed_even_when_pipeline_fails():
    """失敗しても作業ディレクトリを残さない。残すと次のジョブが容量で弾かれる。"""
    drive = MagicMock()
    drive.list_input_raw_videos.return_value = [{"id": "v_001", "name": "t.mp4", "size": 5}]

    def download(file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("raw", encoding="utf-8")
        return True

    drive.download_file_chunked.side_effect = download

    def failing_executor(src, out):
        raise RuntimeError("処理に失敗")

    assert _runner(failing_executor, drive).run_pipeline_for_next_video() is False
    assert not (temp_raw_videos_dir() / "task_v_001").exists()
